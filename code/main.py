from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Any


OUTPUT_COLUMNS = [
    "user_id",
    "image_paths",
    "user_claim",
    "claim_object",
    "evidence_standard_met",
    "evidence_standard_met_reason",
    "risk_flags",
    "issue_type",
    "object_part",
    "claim_status",
    "claim_status_justification",
    "supporting_image_ids",
    "valid_image",
    "severity",
]
CACHE_VERSION = "v2-severity-risk-rubric"

ISSUE_TYPES = {
    "dent",
    "scratch",
    "crack",
    "glass_shatter",
    "broken_part",
    "missing_part",
    "torn_packaging",
    "crushed_packaging",
    "water_damage",
    "stain",
    "none",
    "unknown",
}
OBJECT_PARTS = {
    "car": {
        "front_bumper",
        "rear_bumper",
        "door",
        "hood",
        "windshield",
        "side_mirror",
        "headlight",
        "taillight",
        "fender",
        "quarter_panel",
        "body",
        "unknown",
    },
    "laptop": {
        "screen",
        "keyboard",
        "trackpad",
        "hinge",
        "lid",
        "corner",
        "port",
        "base",
        "body",
        "unknown",
    },
    "package": {
        "box",
        "package_corner",
        "package_side",
        "seal",
        "label",
        "contents",
        "item",
        "unknown",
    },
}
CLAIM_STATUS = {"supported", "contradicted", "not_enough_information"}
SEVERITY = {"none", "low", "medium", "high", "unknown"}
RISK_FLAGS = {
    "none",
    "blurry_image",
    "cropped_or_obstructed",
    "low_light_or_glare",
    "wrong_angle",
    "wrong_object",
    "wrong_object_part",
    "damage_not_visible",
    "claim_mismatch",
    "possible_manipulation",
    "non_original_image",
    "text_instruction_present",
    "user_history_risk",
    "manual_review_required",
}
RISK_FLAG_ORDER = [
    "blurry_image",
    "cropped_or_obstructed",
    "low_light_or_glare",
    "wrong_angle",
    "wrong_object",
    "wrong_object_part",
    "damage_not_visible",
    "claim_mismatch",
    "possible_manipulation",
    "non_original_image",
    "text_instruction_present",
    "user_history_risk",
    "manual_review_required",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def load_env_file(repo_root: Path) -> None:
    """Load OPENAI_API_KEY from .env without requiring notebook env inheritance."""
    candidates = [repo_root / ".env", repo_root.parent / ".env"]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value:
                os.environ.setdefault(key, value)
        return


def image_id(rel_path: str) -> str:
    return Path(rel_path).stem


def parse_claim(text: str, claim_object: str) -> tuple[str, str]:
    t = text.lower()
    issue = "unknown"
    for key, value in [
        ("shatter", "glass_shatter"),
        ("shattered", "glass_shatter"),
        ("crack", "crack"),
        ("cracked", "crack"),
        ("dent", "dent"),
        ("scratch", "scratch"),
        ("scrape", "scratch"),
        ("broken", "broken_part"),
        ("broke", "broken_part"),
        ("missing", "missing_part"),
        ("faltan", "missing_part"),
        ("torn", "torn_packaging"),
        ("open", "torn_packaging"),
        ("crushed", "crushed_packaging"),
        ("dab", "crushed_packaging"),
        ("water", "water_damage"),
        ("wet", "water_damage"),
        ("stain", "stain"),
        ("oily", "stain"),
        ("liquid", "stain"),
    ]:
        if key in t:
            issue = value
            break

    candidates = {
        "car": [
            ("front bumper", "front_bumper"),
            ("rear bumper", "rear_bumper"),
            ("back bumper", "rear_bumper"),
            ("parachoques trasero", "rear_bumper"),
            ("door", "door"),
            ("windshield", "windshield"),
            ("front glass", "windshield"),
            ("side mirror", "side_mirror"),
            ("left mirror", "side_mirror"),
            ("headlight", "headlight"),
            ("taillight", "taillight"),
            ("back light", "taillight"),
            ("fender", "fender"),
            ("body panel", "body"),
            ("body", "body"),
        ],
        "laptop": [
            ("screen", "screen"),
            ("pantalla", "screen"),
            ("keyboard", "keyboard"),
            ("key", "keyboard"),
            ("teclas", "keyboard"),
            ("trackpad", "trackpad"),
            ("hinge", "hinge"),
            ("lid", "lid"),
            ("corner", "corner"),
            ("port", "port"),
            ("base", "base"),
            ("body", "body"),
            ("outer body", "body"),
        ],
        "package": [
            ("corner", "package_corner"),
            ("side", "package_side"),
            ("seal", "seal"),
            ("label", "label"),
            ("contents", "contents"),
            ("item", "item"),
            ("box", "box"),
            ("package", "box"),
            ("parcel", "box"),
        ],
    }
    part = "unknown"
    for key, value in candidates[claim_object]:
        if key in t:
            part = value
            break
    return issue, part


def history_flags(user_id: str, history: dict[str, dict[str, str]]) -> list[str]:
    row = history.get(user_id, {})
    flags = [f for f in row.get("history_flags", "none").split(";") if f and f != "none"]
    try:
        rejected = int(row.get("rejected_claim", "0"))
        recent = int(row.get("last_90_days_claim_count", "0"))
        manual = int(row.get("manual_review_claim", "0"))
    except ValueError:
        rejected = recent = manual = 0
    if rejected >= 3 or recent >= 5:
        flags.append("user_history_risk")
    if manual >= 2:
        flags.append("manual_review_required")
    return sorted(set(flags))


def basic_image_findings(repo_root: Path, image_paths: str) -> dict[str, Any]:
    findings: dict[str, Any] = {"image_ids": [], "missing": [], "quality_flags": []}
    try:
        from PIL import Image, ImageStat
    except Exception:
        return findings

    for rel in image_paths.split(";"):
        p = repo_root / "dataset" / rel
        findings["image_ids"].append(image_id(rel))
        if not p.exists():
            findings["missing"].append(rel)
            continue
        try:
            with Image.open(p) as im:
                w, h = im.size
                gray = im.convert("L").resize((128, 128))
                stat = ImageStat.Stat(gray)
                mean = stat.mean[0]
                extrema = stat.extrema[0]
                if min(w, h) < 220:
                    findings["quality_flags"].append("cropped_or_obstructed")
                if mean < 45 or mean > 225 or extrema[1] - extrema[0] < 35:
                    findings["quality_flags"].append("low_light_or_glare")
        except Exception:
            findings["missing"].append(rel)
    findings["quality_flags"] = sorted(set(findings["quality_flags"]))
    return findings


def build_prompt(row: dict[str, str], user_history: dict[str, str], requirements: list[dict[str, str]]) -> str:
    allowed_parts = sorted(OBJECT_PARTS[row["claim_object"]])
    applicable = [
        r for r in requirements if r["claim_object"] in ("all", row["claim_object"])
    ]
    return (
        "You are verifying a damage claim. Images are the primary source of truth; "
        "the conversation defines what must be checked; history only adds risk context.\n\n"
        f"Claim object: {row['claim_object']}\n"
        f"Conversation: {row['user_claim']}\n"
        f"User history: {json.dumps(user_history, ensure_ascii=False)}\n"
        f"Evidence requirements: {json.dumps(applicable, ensure_ascii=False)}\n\n"
        "Return strict JSON with keys: evidence_standard_met (boolean), "
        "evidence_standard_met_reason, risk_flags (array), issue_type, object_part, "
        "claim_status, claim_status_justification, supporting_image_ids (array), "
        "valid_image (boolean), severity.\n"
        f"Allowed issue_type values: {sorted(ISSUE_TYPES)}.\n"
        f"Allowed object_part values: {allowed_parts}.\n"
        f"Allowed claim_status values: {sorted(CLAIM_STATUS)}.\n"
        f"Allowed risk_flags values: {sorted(RISK_FLAGS)}.\n"
        "Risk flag order, when multiple flags apply, should be: "
        f"{RISK_FLAG_ORDER}.\n"
        "Severity rubric: use none only when no visible relevant damage is present; "
        "use unknown when evidence is insufficient or the object/image is invalid; "
        "use low for minor scratches, missing keycaps, light seal tears, or small stains; "
        "use medium for clear dents, cracks, screen stains, wet/crushed/torn package damage, "
        "or broken mirrors; use high for shattered glass, severe structural deformation, "
        "large broken assemblies, missing contents with visual support, or non-original/wrong-object "
        "evidence attached to a serious claim. Do not leave severity as unknown when the "
        "claim is supported and the damage type is visible.\n"
        "Use issue_type=none only when the relevant part is visible and undamaged. "
        "Use supporting image IDs like img_1, not file paths. Keep reasons concise and image-grounded."
    )


def encode_image(path: Path) -> str:
    # Some corpus files have .jpg names but contain AVIF/WebP bytes. Normalize
    # through Pillow so the API always receives a supported image format.
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            elif im.mode == "L":
                im = im.convert("RGB")
            max_side = max(im.size)
            if max_side > 1600:
                scale = 1600 / max_side
                new_size = (max(1, int(im.width * scale)), max(1, int(im.height * scale)))
                im = im.resize(new_size)
            out = BytesIO()
            im.save(out, format="JPEG", quality=88, optimize=True)
            data = out.getvalue()
    except Exception as exc:
        raise RuntimeError(
            f"Could not normalize image {path}. Install Pillow with AVIF/WebP support "
            "or run with the bundled Codex Python runtime."
        ) from exc
    return f"data:image/jpeg;base64,{base64.b64encode(data).decode('ascii')}"


def call_openai_vlm(
    row: dict[str, str],
    repo_root: Path,
    user_history: dict[str, str],
    requirements: list[dict[str, str]],
    cache_dir: Path,
    model: str,
) -> dict[str, Any] | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(
        (CACHE_VERSION + row["user_claim"] + row["image_paths"] + model).encode("utf-8")
    ).hexdigest()
    cache_path = cache_dir / f"{cache_key}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    content: list[dict[str, Any]] = [{"type": "input_text", "text": build_prompt(row, user_history, requirements)}]
    for rel in row["image_paths"].split(";"):
        content.append({"type": "input_text", "text": f"Image ID: {image_id(rel)}"})
        content.append(
            {
                "type": "input_image",
                "image_url": encode_image(repo_root / "dataset" / rel),
                "detail": "high",
            }
        )
    payload = {
        "model": model,
        "temperature": 0,
        "input": [{"role": "user", "content": content}],
        "text": {"format": {"type": "json_object"}},
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            text = extract_response_text(body)
            parsed = json.loads(text)
            cache_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
            return parsed
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            print(f"OpenAI API error for {row['user_id']} ({exc.code}): {error_body[:500]}")
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
            if attempt == 3:
                return None
            time.sleep(2**attempt)
    return None


def extract_response_text(body: dict[str, Any]) -> str:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    for item in body.get("output", []):
        for part in item.get("content", []):
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                return part["text"]
    raise KeyError("No output_text found in OpenAI response")


def heuristic_prediction(
    row: dict[str, str],
    repo_root: Path,
    history: dict[str, dict[str, str]],
) -> dict[str, Any]:
    issue, part = parse_claim(row["user_claim"], row["claim_object"])
    findings = basic_image_findings(repo_root, row["image_paths"])
    flags = findings["quality_flags"] + history_flags(row["user_id"], history)
    if re.search(r"approve|ignore|skip|instruction", row["user_claim"], re.I):
        flags.append("text_instruction_present")
        flags.append("manual_review_required")
    valid = not findings["missing"]
    enough = valid and part != "unknown"
    status = "not_enough_information" if not enough else "supported"
    supporting = findings["image_ids"][:1] if enough else []
    return {
        "evidence_standard_met": enough,
        "evidence_standard_met_reason": (
            "At least one submitted image is available for the claimed object part."
            if enough
            else "The submitted evidence is missing or the claimed part cannot be determined."
        ),
        "risk_flags": sorted(set(flags)) or ["none"],
        "issue_type": issue,
        "object_part": part,
        "claim_status": status,
        "claim_status_justification": (
            f"Automated fallback extracted a {issue} claim for {part}; use VLM review for final visual confirmation."
            if enough
            else "Automated fallback could not confirm the visual evidence for the claimed part."
        ),
        "supporting_image_ids": supporting,
        "valid_image": valid,
        "severity": "unknown" if issue == "unknown" else ("medium" if issue in {"dent", "crack", "glass_shatter", "broken_part"} else "low"),
    }


def ordered_risk_flags(flags: list[str]) -> list[str]:
    cleaned = [flag for flag in flags if flag in RISK_FLAGS and flag != "none"]
    ordered = [flag for flag in RISK_FLAG_ORDER if flag in set(cleaned)]
    return ordered or ["none"]


def calibrate_severity(
    claim_object: str,
    issue: str,
    part: str,
    status: str,
    valid_image: bool,
    current: str,
    risk_flags: list[str],
) -> str:
    if not valid_image or status == "not_enough_information":
        return "unknown"
    if issue == "none" or status == "contradicted":
        if status == "contradicted" and "claim_mismatch" in risk_flags and "non_original_image" not in risk_flags:
            if issue in {"scratch", "dent", "crack", "torn_packaging", "crushed_packaging"}:
                return "low"
        if "wrong_object" in risk_flags or "non_original_image" in risk_flags:
            if claim_object == "car":
                return "high"
            if claim_object == "package":
                return "low"
        return "none"

    if claim_object == "car":
        if issue == "scratch":
            return "low"
        if issue in {"dent", "crack"}:
            return "medium"
        if issue == "broken_part" and part == "side_mirror":
            return "medium"
        if issue in {"glass_shatter", "broken_part"}:
            return "high"

    if claim_object == "laptop":
        if part == "trackpad" and issue in {"scratch", "none"}:
            return "none"
        if part == "corner" and issue == "dent":
            return "low"
        if part == "keyboard" and issue == "missing_part":
            return "low"
        if part in {"screen", "hinge"} and issue in {"crack", "broken_part", "glass_shatter"}:
            return "medium"
        if issue == "stain":
            return "medium"

    if claim_object == "package":
        if issue == "missing_part" and part in {"contents", "item"}:
            return "unknown"
        if issue == "torn_packaging" and part == "seal":
            return "medium"
        if issue in {"torn_packaging", "stain"}:
            return "low"
        if issue == "crushed_packaging" and part == "package_side":
            return "low"
        if issue in {"crushed_packaging", "water_damage"}:
            return "medium"

    if current in {"low", "medium", "high", "none"}:
        return current
    if issue in {"glass_shatter"}:
        return "high"
    if issue in {"dent", "crack", "water_damage", "stain"}:
        return "medium"
    if issue == "broken_part":
        return "medium" if part in {"side_mirror", "hinge"} else "high"
    if issue in {"scratch", "missing_part", "torn_packaging"}:
        return "low"
    if issue == "crushed_packaging":
        return "medium"
    return "unknown"


def normalize_prediction(pred: dict[str, Any], row: dict[str, str], history_row: dict[str, str]) -> dict[str, str]:
    def bool_str(value: Any) -> str:
        return "true" if bool(value) else "false"

    risk = pred.get("risk_flags", ["none"])
    if isinstance(risk, str):
        risk_list = [x for x in risk.split(";") if x]
    else:
        risk_list = [str(x) for x in risk if x]
    history_risk = [x for x in history_row.get("history_flags", "none").split(";") if x and x != "none"]
    risk_list.extend(history_risk)
    risk_list = ordered_risk_flags(risk_list)

    supporting = pred.get("supporting_image_ids", [])
    if isinstance(supporting, str):
        supporting_list = [x for x in supporting.split(";") if x and x != "none"]
    else:
        supporting_list = [str(x) for x in supporting if x]

    issue = str(pred.get("issue_type", "unknown"))
    if issue not in ISSUE_TYPES:
        issue = "unknown"
    part = str(pred.get("object_part", "unknown"))
    if part not in OBJECT_PARTS[row["claim_object"]]:
        part = "unknown"
    status = str(pred.get("claim_status", "not_enough_information"))
    if status not in CLAIM_STATUS:
        status = "not_enough_information"

    claimed_issue, claimed_part = parse_claim(row["user_claim"], row["claim_object"])
    claim_text = row["user_claim"].lower()

    if row["claim_object"] == "laptop" and issue in {"glass_shatter", "water_damage"}:
        issue = "crack" if issue == "glass_shatter" else "stain"
    if row["claim_object"] == "car" and part == "side_mirror" and issue == "crack":
        issue = "broken_part"
    if claimed_issue == "scratch" and issue in {"dent", "crack", "unknown"}:
        issue = "scratch"
    if row["claim_object"] == "laptop" and part == "trackpad" and issue == "scratch":
        if any(word in claim_text for word in ["not working", "function", "stopped working", "respond"]):
            issue = "none"
            status = "contradicted"
            if "damage_not_visible" not in risk_list:
                risk_list = ordered_risk_flags(risk_list + ["damage_not_visible"])
    if row["claim_object"] == "package" and part in {"contents", "item"} and issue == "missing_part":
        if "missing" in claim_text or "not inside" in claim_text:
            issue = "unknown"
            status = "not_enough_information"
            if "damage_not_visible" not in risk_list:
                risk_list = ordered_risk_flags(risk_list + ["damage_not_visible"])
            valid_for_missing = False
        else:
            valid_for_missing = True
    else:
        valid_for_missing = True

    try:
        manual_reviews = int(history_row.get("manual_review_claim", "0"))
    except ValueError:
        manual_reviews = 0
    if "user_history_risk" in risk_list and manual_reviews >= 2:
        risk_list = ordered_risk_flags(risk_list + ["manual_review_required"])

    if status == "contradicted" and "claim_mismatch" in risk_list and "wrong_object" not in risk_list:
        if claimed_issue != "unknown":
            issue = claimed_issue
        if claimed_part != "unknown":
            part = claimed_part
    severity = str(pred.get("severity", "unknown"))
    if severity not in SEVERITY:
        severity = "unknown"
    severity = calibrate_severity(
        claim_object=row["claim_object"],
        issue=issue,
        part=part,
        status=status,
        valid_image=bool(pred.get("valid_image", False)),
        current=severity,
        risk_flags=risk_list,
    )

    evidence_met = bool(pred.get("evidence_standard_met", False))
    if status in {"supported", "contradicted"} and supporting_list:
        evidence_met = True
    if status == "not_enough_information":
        evidence_met = False
    if not valid_for_missing:
        evidence_met = False

    if status == "not_enough_information":
        supporting_list = []
    elif len(supporting_list) > 1:
        justification = str(pred.get("claim_status_justification", "")).lower()
        mentioned = [img for img in supporting_list if img.lower() in justification]
        if mentioned:
            supporting_list = mentioned
        elif "second image" in justification and "img_2" in supporting_list:
            supporting_list = ["img_2"]

    return {
        "user_id": row["user_id"],
        "image_paths": row["image_paths"],
        "user_claim": row["user_claim"],
        "claim_object": row["claim_object"],
        "evidence_standard_met": bool_str(evidence_met),
        "evidence_standard_met_reason": str(pred.get("evidence_standard_met_reason", ""))[:500],
        "risk_flags": ";".join(risk_list),
        "issue_type": issue,
        "object_part": part,
        "claim_status": status,
        "claim_status_justification": str(pred.get("claim_status_justification", ""))[:500],
        "supporting_image_ids": ";".join(supporting_list) if supporting_list else "none",
        "valid_image": bool_str(pred.get("valid_image", False)),
        "severity": severity,
    }


def run(
    input_csv: Path,
    output_csv: Path,
    repo_root: Path,
    model: str,
    use_vlm: bool,
) -> list[dict[str, str]]:
    load_env_file(repo_root)
    rows = read_csv(input_csv)
    history_rows = {r["user_id"]: r for r in read_csv(repo_root / "dataset" / "user_history.csv")}
    requirements = read_csv(repo_root / "dataset" / "evidence_requirements.csv")
    output: list[dict[str, str]] = []
    for row in rows:
        hrow = history_rows.get(row["user_id"], {})
        pred = None
        if use_vlm:
            pred = call_openai_vlm(row, repo_root, hrow, requirements, repo_root / "code" / ".cache", model)
        if pred is None:
            pred = heuristic_prediction(row, repo_root, history_rows)
        output.append(normalize_prediction(pred, row, hrow))
    write_csv(output_csv, output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-modal evidence review agent")
    parser.add_argument("--input", default="dataset/claims.csv", type=Path)
    parser.add_argument("--output", default="output.csv", type=Path)
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument("--model", default=os.environ.get("OPENAI_VISION_MODEL", "gpt-4.1-mini"))
    parser.add_argument("--no-vlm", action="store_true", help="Disable OPENAI_API_KEY VLM calls and use fallback only")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    run(
        input_csv=(repo_root / args.input).resolve() if not args.input.is_absolute() else args.input,
        output_csv=(repo_root / args.output).resolve() if not args.output.is_absolute() else args.output,
        repo_root=repo_root,
        model=args.model,
        use_vlm=not args.no_vlm,
    )


if __name__ == "__main__":
    main()
