"""
Bulk Excel/CSV importer.

Handles the "upload the Excel/CSV in the given template format -> parse ->
create records -> refresh dashboard" workflow described in the requirements
document. One generic engine drives every form type (Activity Report,
10 screening tools, Training Attendance) by normalising headers and mapping
them onto known field aliases pulled directly from the client's templates.

Any header that isn't recognised as a "core" field is preserved verbatim
inside the record's `details` JSONField, so no data from the source Excel
sheet is ever silently dropped.
"""
import datetime
import io
import re

import pandas as pd
from django.db import transaction
from django.utils import timezone

from core.models import Region, LocalCouncil, JamatKhana, Portfolio, Program
from .models import (
    ActivityReport, Participant, TrainingProgram, TrainingAttendance,
    SCREENING_MODELS, UploadBatch,
)

SCREENING_PORTFOLIO_NAME = "Health Screening"


def get_screening_program(model_key, model):
    """Every screening record is linked to a Program under a single
    'Health Screening' Portfolio, so portfolio-wise / program-wise analysis
    works consistently across all dashboards."""
    portfolio, _ = Portfolio.objects.get_or_create(name=SCREENING_PORTFOLIO_NAME)
    program, _ = Program.objects.get_or_create(portfolio=portfolio, name=model._meta.verbose_name)
    return program


def normalize_header(h):
    h = str(h).strip().lower()
    h = re.sub(r"[^a-z0-9]+", "_", h)
    return h.strip("_")


# Canonical field -> list of header variants (already normalized) seen across
# the Kobo and AKHSP templates supplied for the 10 screening tools.
ALIASES = {
    "date": ["date", "date_of_screening", "date_of_examination", "date_of_assessment", "start", "screening_date"],
    "region": ["region"],

    "local_council": ["local_council", "local", "council", "jurisdiction"],  # Mammogram uses "Jurisdiction"

    "jamat_khana": [
        "jamat_khana", "jammat_khana", "jamatkhana", "venue_jamatkhana", "venue", "center",
        "jamat_khana_venue",      # Adolescent: "Jamat Khana/Venue"
        "name_of_jamatkhana",     # Dass: "Name of JamatKhana"
    ],

    "full_name": ["full_name", "name", "participant_name"],

    "father_husband_name": [
        "father_s_name", "father_husband_name", "father_name", "father_husband_name_",
        "father_spouse_name", "father_mother_self",
        "father_sppouse_name",    # ICOPE typo: "Father/Sppouse Name"
    ],

    "cnic": ["cnic", "cnic_number", "cnic_nic_number", "cnic_father_mother_self"],
    "age": ["age", "age_12_18"],
    "gender": ["gender", "gender_m_f"],
    "contact_number": ["contact_number", "cell_number", "contact"],

    "referred": [
        "referred", "reffer", "refer", "referred_yes_no",
        "referred_for_further_checkups_yes_no", "have_you_referred_the_senior_for_further_check_ups",
        "total_referrals",
        "referral",                                            # Kobo Dass: "Referral"
        "referred_by_formula",                                 # HBA1C: "Referred BY Formula"
        "reffered_by_formula",                                 # Kobo ICOPE typo: "Reffered By Formula"
        "have_you_referred_the_senior_for_futher_check_ups",   # Kobo typo: "futher" not "further"
    ],

    "reason_for_referral": [
        "reason_of_referrals", "reason_for_referrals", "reason_of_referrals_recommendations",
        "if_yes_please_select_reason_for_referral", "recommendations_additional_remarks",
        "refered_for",             # ICOPE: "Refered For"
    ],

    "remarks": [
        "remarks", "open_comments", "comments_if_any", "physician_s_recommendation",
        "physicican_s_reccomendation",   # ICOPE typo: "Physicican's Reccomendation"
    ],
    # NOTE: deliberately no "risk_category" canonical field/alias here.
    # Columns like "BP", "BP/BMI Status", "Diagnosis/Findings", or
    # "Mammography Findings Normal/Abnormal" fall through to `details`
    # (the leftover JSON) like any other unrecognised column, guaranteeing
    # they're never silently discarded. infer_risk_category() below then
    # reads them back out of `details` on a best-effort basis to populate
    # the structured risk_category field, without ever removing them from
    # `details` - the raw value stays visible either way.
    "depression_score": ["depression_score"],
    "anxiety_score": ["anxiety_score"],
    "stress_score": ["stress_score"],
    # Activity report specific
    "venue_ar": ["venue"],
    "portfolio": ["portfolio"],
    "program": ["program"],
    "name_of_activity": ["name_of_activity"],
    "description": ["description"],
    "number_of_beneficiaries": ["number_of_beneficiaries"],
    "facilitator_trainer": ["facilitator_trainer"],
    "collaboration": ["collaboration"],
    # Training specific
    "training_title": ["training_title", "title"],
    "trainer_name": ["trainer_name"],
    "training_duration": ["training_duration", "duration_hours"],
    "target_audience": ["target_audience"],
    "number_of_participants": ["number_of_participants"],
    "institution_organization": ["institution_organization", "institution"],
    "designation_title": ["designation_title", "designation"],
    "attendance_status": ["attendance_status"],
}

REVERSE_ALIASES = {}
for canon, variants in ALIASES.items():
    for v in variants:
        REVERSE_ALIASES.setdefault(v, canon)


# ---------------------------------------------------------------------------
# Downloadable, form-type-specific bulk upload templates.
#
# Every header list below is the EXACT header set from the client's official
# AKHSP template for that screening tool (cross-checked against the supplied
# "Templates_of_headers_for_MIS.xlsx" reference sheet and the real column
# order used in "2026_Screenings-data-smpl.xlsx"). Any column not consumed
# by a canonical ALIASES entry above still round-trips safely into that
# record's `details` JSONField - nothing from these headers is ever dropped,
# whether or not it maps to a structured column.
# ---------------------------------------------------------------------------
COMMON_SCREENING_HEADERS = [
    "Date of Screening", "Full Name", "Father/Husband Name", "CNIC",
    "Age", "Gender (M/F)", "Contact Number",
    "Region", "Local Council", "Jamat Khana",
    "Referred (Yes/No)", "Reason for Referrals", "Remarks",
]

ACTIVITY_REPORT_HEADERS = [
    "Date", "Region", "Local Council", "Jamat Khana", "Portfolio", "Program",
    "Name of Activity", "Description", "Number of Beneficiaries",
    "Facilitator/Trainer", "Collaboration", "Remarks",
]

TRAINING_ATTENDANCE_HEADERS = [
    "Training Title", "Date", "Region", "Local Council", "Jamat Khana",
    "Portfolio", "Program", "Trainer Name", "Training Duration",
    "Target Audience", "Full Name", "CNIC", "Contact Number",
    "Institution/Organization", "Designation/Title", "Attendance Status",
]

CARDIAC_HEADERS = [
    "Date of Screening", "Months", "Full Name", "Father/Husband Name", "CNIC", "Age", "Gender M/F",
    "Contact Number", "Region", "Local council", "Jamat Khana", "Any Medical History(BP etc.)",
    "History of Smoking, Alcohol, and Substance use", "height (CM)", "weight (KG)", "BMI",
    "Systolic SBP", "diastolic DBP", "Referred", "Recommendations /Additional Remarks:",
]

ADOLESCENT_HEADERS = [
    "Date of Assessment", "Month", "Full Name", "Father/ Husband Name", "Age (12-18)", "Gender",
    "Contact Number", "Region", "Local council", "Jamat Khana/Venue", "Height (In CM)", "Weight (Kgs)",
    "Temperature", "Blood Pressure", "Hair", "Scalp", "Nasal Septum", "External Ear", "Hearing",
    "Teeth/ Dental", "Tonsils", "Vision", "Personal Hygiene", "Nutrition Status",
    "HB test (Anemia)-Score", "HB Status", "Referred for further checkups. Yes / No", "Reason of Referrals",
]

CBE_HEADERS = [
    "Date of Examination", "Month", "Full Name", "Father/husband Name", "CNIC", "Age", "Contact Number",
    "Marital Status (Single/Married)", "Region", "Local council", "Jamat Khana",
    "Family History of Breast Cancer (if any)", "Any history of breast lump or surgery Yes/NO",
    "Currently taking any medication? Yes/no",
    "1. Normal (2). Breast Pain 3. Abnormal Lymph nodes 4. Lump (5). Any other",
    "Reffer", "Recommendations/Additional Remarks",
]

DASS_HEADERS = [
    "Date of Assessment", "Month", "Full Name", "Father/Husband Name", "CNIC", "Age", "Gender",
    "Contact Number", "Region", "Local Council", "Name of JamatKhana", "Depression Score",
    "Anxiety Score", "Stress Score", "Level of Depression", "Level of Anxiety", "Level of Stress",
    "Referred for further checkups. Yes / No", "Recommendations / Additional Remarks",
]

ICOPE_HEADERS = [
    "Region", "Council", "Center", "Date of Screening", "Month", "Screening conducted at:", "Activity",
    "Consent for Data Sharing", "Name", "Father/Sppouse Name", "DOB", "CNIC Number", "Age",
    "Age Categories", "Gender", "Marital Status", "Contact #", "Weight (Kg)", "Height (cm)", "BMI",
    "BMI Categories", "Body Temperature (°C)", "Blood Pressure (mm/Hg)", "Categories for BP",
    "Heart rate", "Respiratory rate", "SpO2", "Pain Status", "Location of Pain", "Pain Scale",
    "Known Medical History", "Known Medications Usage", "Left Eye", "Right Eye", "Eye Results",
    "Whisper Test", "Depression Screening", "Nutrition Screening", "Physical Activity Screening",
    "Cognition Screening", "Referral", "Refered For", "Comments (if any)", "Physicican's Reccomendation",
]

EYE_HEADERS = [
    "Date of Screening", "Month", "Full Name", "Father Name", "CNIC (father/Mother/Self)", "Age",
    "Gender", "Contact Number", "Region", "Local council", "Jamat Khana",
    "Any Medical History(eg.Bp, CA,HDL)", "Left Eye Normal/Abnormal", "Right Eye Normal/Abnormal",
    "Diagnosis/ Findings", "Referred Yes / No", "Reason of Referrals",
]

CAMP_HEADERS = [
    "Date of Screening", "Month", "Full Name", "Father Name", "CNIC", "Age", "Gender M / F",
    "Contact Number", "Region", "Local council", "Jamat Khana",
    "Any Medical History BP,DM,CVD,SMK,CKD Others", "Currently taking any medications?", "Temperature",
    "Heart Rate (Pulse)", "Blood Pressure", "Height (CM)", "Weight", "Waist Circumference (CM)", "BMI",
    "Blood Sugar (RBS) /HBA1c", "cholesterol", "Eyes/Vision", "Ears/Hearing", "Nose", "Throat", "Skin",
    "Any Physical Finding", "Referred for further checkups. Yes / No", "Reason of Referrals /Recommendations",
]

MAMMOGRAM_HEADERS = [
    "Date of Examination", "Month", "NAME", "Father/husband Name", "CNIC", "AGE", "Contact Number",
    "Marital Status (Single/Married)", "Region", "Jurisdiction", "Jamat Khana",
    "Family History of Breast Cancer (if any)", "Any history of breast lump or surgery",
    "Currently taking any medication?", "Date of CBE",
    "1. Normal (2). Breast Pain 3. Abnormal Lymph nodes 4. Lump (5). Any other",
    "Mammography Findings Normal/Abnormal", "Recommendations/Additional Remarks",
]

HBA1C_HEADERS = [
    "Date of Screening", "Month", "Full Name", "Father/Husband Name", "CNIC", "Age", "Age Group",
    "Gender M/F", "Contact Number", "Region", "Local council", "Jamat Khana", "any Medical history",
    "HBA1C %", "Referred BY Formula", "Remarks",
]

TEMPLATE_HEADERS = {
    "ACTIVITY_REPORT": ACTIVITY_REPORT_HEADERS,
    "cardiac_risk_assessment": CARDIAC_HEADERS,
    "mental_health_dass21": DASS_HEADERS,
    "clinical_breast_examination": CBE_HEADERS,
    "mammogram_screening": MAMMOGRAM_HEADERS,
    "elderly_eye_screening": EYE_HEADERS,
    "adolescent_health_screening": ADOLESCENT_HEADERS,
    "hba1c_screening": HBA1C_HEADERS,
    "nutrition_assessment": COMMON_SCREENING_HEADERS,  # no official template supplied yet - flag with client
    "elderly_neurological_assessment": ICOPE_HEADERS,
    "adult_health_screening": CAMP_HEADERS,
    "TRAINING_ATTENDANCE": TRAINING_ATTENDANCE_HEADERS,
}


def build_upload_template(form_type):
    """Returns an in-memory .xlsx (BytesIO) for form_type with:
      - a "Template" sheet (sheet index 0 - this MUST stay first, since
        bulk upload only ever reads the first sheet of an uploaded file)
        with a single bold header row matching exactly what import_*()
        expects, Date column(s) pre-formatted as text so Excel never
        silently reformats a typed date into a different locale/format,
        and a cell comment on each Date header spelling out the required
        format;
      - an "Instructions" sheet (deliberately placed AFTER "Template", not
        before it) with plain-language notes on format, geography and
        data-preservation rules.
    Returns None for an unrecognised form_type.
    """
    headers = TEMPLATE_HEADERS.get(form_type)
    if headers is None:
        return None

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.comments import Comment

    wb = Workbook()
    ws = wb.active
    ws.title = "Template"
    ws.append(headers)

    header_fill = PatternFill(start_color="0B5D63", end_color="0B5D63", fill_type="solid")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill

    date_format_note = (
        f"Required format: {DATE_FORMAT_HINT}.\nNo other format is accepted - a row with a "
        f"date in any other format is rejected with an error, not silently guessed or defaulted."
    )
    for i, header in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(16, len(header) + 4)
        if "date" in header.lower():
            header_cell = ws.cell(row=1, column=i)
            header_cell.comment = Comment(date_format_note, "Health Programs DMS")
            # Force this column's data cells to plain text so Excel never
            # auto-converts a typed "2026-03-05" into a locale-specific
            # date serial that could read back differently.
            col_letter = get_column_letter(i)
            for r in range(2, 202):
                ws.cell(row=r, column=i).number_format = "@"

    ws.freeze_panes = "A2"

    # --- Instructions sheet (kept AFTER "Template" - see docstring) -------
    instructions = wb.create_sheet("Instructions")
    instructions.column_dimensions["A"].width = 110
    instructions["A1"] = "How to fill in this template"
    instructions["A1"].font = Font(bold=True, size=13, color="0B5D63")

    lines = [
        "",
        "1. Fill in one row per record on the 'Template' sheet. Keep the header row (row 1) exactly as-is -",
        "   renaming, reordering or deleting header columns will stop them being recognised on upload.",
        "",
        f"2. Any 'Date' column must be entered as {DATE_FORMAT_HINT}. This is the ONLY accepted format.",
        "   Dates in any other format (DD/MM/YYYY, MM/DD/YYYY, '5 March 2026', etc.), or an invalid calendar",
        "   date (e.g. 29 February in a non-leap year), will cause that row to be rejected with a clear error",
        "   instead of being imported with a guessed or default date.",
        "",
        "3. Region, Local Council and Jamatkhana values must already exist in the system - bulk upload never",
        "   creates new geography. If a row references one that doesn't exist yet, add it first via Django",
        "   Admin (National Admins only), then re-upload.",
        "",
        "4. Extra columns you add beyond the given headers are kept and stored against each record rather than",
        "   discarded; recognised columns (Region, Full Name, Referred, etc.) are validated and structured.",
        "",
        "5. A row that fails validation (missing required field, unknown geography, bad date, etc.) is skipped",
        "   with its row number and reason reported after upload - it does not stop the rest of the file from",
        "   importing.",
    ]
    for offset, line in enumerate(lines, start=2):
        instructions[f"A{offset}"] = line

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def map_row_to_canonical(row_dict):
    """row_dict: {normalized_header: value}. Returns (canonical_dict, leftover_dict)."""
    canonical, leftover, raw_headers_used = {}, {}, {}
    for header, value in row_dict.items():
        canon = REVERSE_ALIASES.get(header)
        if canon and canon not in canonical:
            canonical[canon] = value
            raw_headers_used[canon] = header
        else:
            leftover[header] = value
    return canonical, leftover


# Any leftover column whose normalized name contains one of these substrings
# is treated as a possible clinical risk/finding indicator (e.g. "BP/BMI
# Status", "Diagnosis/Findings", "Mammography Findings Normal/Abnormal").
RISK_HINT_KEY_SUBSTRINGS = ("diagnosis", "finding", "risk_categ", "bp_bmi_status")


def infer_risk_category(leftover):
    """
    Best-effort risk categorization, read from columns already sitting in
    `leftover` (i.e. columns that don't map to any other recognised field).
    This NEVER removes anything from `leftover` - the raw value is always
    still saved verbatim in the record's `details` JSON regardless of what
    this function decides, so a wrong or missed inference never loses data,
    it only affects the structured risk_category field used for dashboard
    filtering/reporting.

    HIGH takes priority if multiple risk-hint columns disagree, since that's
    the safer (more clinically conservative) reading of ambiguous data.
    """
    found = None
    for key, value in leftover.items():
        if not any(hint in key for hint in RISK_HINT_KEY_SUBSTRINGS):
            continue
        text = str(value).strip().lower()
        if not text:
            continue
        if "abnormal" in text or "high" in text:
            return "HIGH"
        if "moderate" in text:
            found = found or "MODERATE"
        elif "normal" in text or "low" in text:
            found = found or "LOW"
    return found or "UNKNOWN"


TRUE_VALUES = {"yes", "y", "true", "1", "referred", "abnormal", "high"}


def to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in TRUE_VALUES


DATE_FORMATS = ("%d-%m-%Y", "%Y-%m-%d %H:%M:%S")
DATE_FORMAT_HINT = "DD-MM-YYYY (e.g. 05-03-2026)"


def parse_date(value, field_label="Date"):
    """
    STRICT date parsing - exactly one human-entered format is accepted:
    DD-MM-YYYY (e.g. 05-03-2026). The second accepted pattern,
    YYYY-MM-DD HH:MM:SS, isn't a second "allowed format" for typers - it's
    the literal string pandas/openpyxl produce for a genuine Excel date
    cell regardless of that cell's display format, so it has to stay
    accepted or every real Excel date column would be rejected outright.
    Anything else - other separators, month-first/ISO text like
    "2026-03-05", an invalid calendar date (e.g. 29 Feb in a non-leap
    year), or a blank cell - is REJECTED for that row with a clear error,
    rather than silently defaulting to today's date. Bad dates must be
    fixed and re-uploaded, not guessed at.
    """
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value

    text = str(value).strip() if value is not None else ""
    if not text:
        raise ImportError_(f"{field_label} is required and must be in {DATE_FORMAT_HINT} format.")

    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    raise ImportError_(
        f"{field_label} '{text}' is not a valid date in the required {DATE_FORMAT_HINT} format "
        f"(other formats/separators, e.g. YYYY-MM-DD or MM-DD-YYYY, are not accepted)."
    )

def get_geo(region_name, local_council_name, jamat_khana_name):
    """
    Cross-checks Region / Local Council / Jamatkhana against records that
    already exist in the system - bulk uploads NEVER create new geography.

    This keeps the reference geography clean (no typos or duplicate
    Region/Local Council/Jamatkhana rows sneaking in through spreadsheet
    uploads). New Regions/Local Councils must be added first via
    "Regions & Local Councils" in the app (National Admins), and new
    Jamatkhanas via Django Admin - then the bulk upload will resolve them
    correctly.

    Raises ImportError_ (caught by the caller, logged as a row-level error)
    if a named Region/Local Council/Jamatkhana isn't found.
    """
    region_name = str(region_name).strip() if region_name is not None else ""
    if not region_name:
        raise ImportError_(
            "Region is required and must already exist in the system "
            "(add it via 'Regions & Local Councils' first)."
        )
    try:
        region = Region.objects.get(name__iexact=region_name)
    except Region.DoesNotExist:
        raise ImportError_(
            f"Region '{region_name}' was not found. Add it via 'Regions & "
            f"Local Councils' before importing."
        )
    except Region.MultipleObjectsReturned:
        region = Region.objects.filter(name__iexact=region_name).first()

    local_council_name = str(local_council_name).strip() if local_council_name is not None else ""
    if not local_council_name:
        raise ImportError_(
            "Local Council is required and must already exist under the "
            "given Region (add it via 'Regions & Local Councils' first)."
        )
    try:
        local_council = LocalCouncil.objects.get(region=region, name__iexact=local_council_name)
    except LocalCouncil.DoesNotExist:
        raise ImportError_(
            f"Local Council '{local_council_name}' was not found under "
            f"Region '{region_name}'. Add it via 'Regions & Local Councils' "
            f"before importing."
        )
    except LocalCouncil.MultipleObjectsReturned:
        local_council = LocalCouncil.objects.filter(region=region, name__iexact=local_council_name).first()

    jamat_khana = None
    jamat_khana_name = str(jamat_khana_name).strip() if jamat_khana_name is not None else ""
    if jamat_khana_name:
        try:
            jamat_khana = JamatKhana.objects.get(local_council=local_council, name__iexact=jamat_khana_name)
        except JamatKhana.DoesNotExist:
            raise ImportError_(
                f"Jamatkhana '{jamat_khana_name}' was not found under Local "
                f"Council '{local_council_name}'. Add it via Django Admin "
                f"before importing."
            )
        except JamatKhana.MultipleObjectsReturned:
            jamat_khana = JamatKhana.objects.filter(local_council=local_council, name__iexact=jamat_khana_name).first()

    return region, local_council, jamat_khana


# Backwards-compatible alias in case anything still imports the old name.
get_or_create_geo = get_geo


def read_dataframe(uploaded_file):
    """Reads a single dataframe: the only sheet for CSV, or sheet 0 for a
    single-sheet Excel file. For a multi-sheet Excel file, use
    read_all_sheets() instead - this function intentionally stays "first
    sheet only" for callers (e.g. a direct single-form-type re-read) that
    already know they're dealing with one sheet."""
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file, dtype=str, keep_default_na=False)
    return pd.read_excel(uploaded_file, dtype=str, keep_default_na=False)



def _drop_blank_rows(df):
    """Drops rows where every cell is blank/whitespace - harmless padding
    rows (common at the bottom of a sheet sized to e.g. 200 rows) shouldn't
    be counted or reported as validation errors. Preserves the original
    index, so row-number-in-error-messages (idx + 2) still matches the
    real spreadsheet row."""
    if df.empty:
        return df
    mask = df.apply(lambda row: any(str(v).strip() for v in row), axis=1)
    return df[mask]



class ImportError_(Exception):
    pass


def _clean(v):
    if v is None:
        return ""
    v = str(v).strip()
    return "" if v.lower() == "nan" else v


def import_screening_form(df, model_key, user):
    """Generic importer for any of the 10 screening tools -> Participant + Screening record."""
    model = SCREENING_MODELS[model_key]
    success, errors = 0, []

    for idx, row in df.iterrows():
        row_num = idx + 2  # account for header row, 1-indexed
        try:
            row_dict = {normalize_header(k): _clean(v) for k, v in row.to_dict().items()}
            canonical, leftover = map_row_to_canonical(row_dict)

            if not canonical.get("full_name"):
                raise ImportError_("Missing required field: Full Name")

            with transaction.atomic():
                region, local_council, jamat_khana = get_geo(
                    canonical.get("region"), canonical.get("local_council"), canonical.get("jamat_khana")
                )

                age_val = canonical.get("age")
                try:
                    age_val = int(float(age_val)) if age_val else None
                except (ValueError, TypeError):
                    age_val = None

                gender_raw = (canonical.get("gender") or "").strip().upper()[:1]
                gender = gender_raw if gender_raw in ("M", "F", "O") else "O"

                participant = Participant.objects.create(
                    region=region,
                    local_council=local_council,
                    jamat_khana=jamat_khana,
                    full_name=canonical.get("full_name"),
                    father_husband_name=canonical.get("father_husband_name", ""),
                    cnic=canonical.get("cnic", ""),
                    contact_number=canonical.get("contact_number", ""),
                    gender=gender,
                    age=age_val,
                    venue=canonical.get("jamat_khana", ""),
                    created_by=user,
                )

                record_kwargs = dict(
                    participant=participant,
                    program=get_screening_program(model_key, model),
                    region=region,
                    local_council=local_council,
                    jamat_khana=jamat_khana,
                    screening_date=parse_date(canonical.get("date"), field_label="Date of Screening"),
                    source=UploadBatch.FormType(model_key).label,
                    referred=to_bool(canonical.get("referred")),
                    reason_for_referral=canonical.get("reason_for_referral", "")[:250],
                    risk_category=infer_risk_category(leftover),
                    remarks=canonical.get("remarks", ""),
                    details=leftover,
                    created_by=user,
                )
                if hasattr(model, "depression_score"):
                    record_kwargs.update(
                        depression_score=_safe_int(canonical.get("depression_score")),
                        anxiety_score=_safe_int(canonical.get("anxiety_score")),
                        stress_score=_safe_int(canonical.get("stress_score")),
                    )
                model.objects.create(**record_kwargs)
            success += 1
        except Exception as exc:  # noqa: BLE001 - collect and continue
            errors.append({"row": row_num, "error": str(exc)})

    return success, errors


def _safe_int(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def import_activity_report(df, user):
    success, errors = 0, []
    for idx, row in df.iterrows():
        row_num = idx + 2
        try:
            row_dict = {normalize_header(k): _clean(v) for k, v in row.to_dict().items()}
            canonical, leftover = map_row_to_canonical(row_dict)
            if not canonical.get("name_of_activity"):
                raise ImportError_("Missing required field: Name of Activity")

            with transaction.atomic():
                region, local_council, jamat_khana = get_geo(
                    canonical.get("region"), canonical.get("local_council"), canonical.get("jamat_khana")
                )
                portfolio, _ = Portfolio.objects.get_or_create(name=canonical.get("portfolio") or "General")
                program, _ = Program.objects.get_or_create(portfolio=portfolio, name=canonical.get("program") or "General")

                ActivityReport.objects.create(
                    date=parse_date(canonical.get("date"), field_label="Date"),
                    region=region, local_council=local_council, jamat_khana=jamat_khana,
                    venue=canonical.get("jamat_khana") or canonical.get("venue_ar") or "",
                    portfolio=portfolio, program=program,
                    name_of_activity=canonical.get("name_of_activity"),
                    description=canonical.get("description", ""),
                    number_of_beneficiaries=_safe_int(canonical.get("number_of_beneficiaries")) or 0,
                    facilitator_trainer=canonical.get("facilitator_trainer", ""),
                    collaboration=canonical.get("collaboration", ""),
                    remarks=canonical.get("remarks", ""),
                    created_by=user,
                )
            success += 1
        except Exception as exc:
            errors.append({"row": row_num, "error": str(exc)})
    return success, errors


def import_training_attendance(df, user):
    """Expects a `Training Title` column repeated per attendee row, plus attendee fields."""
    success, errors = 0, []
    training_cache = {}
    for idx, row in df.iterrows():
        row_num = idx + 2
        try:
            row_dict = {normalize_header(k): _clean(v) for k, v in row.to_dict().items()}
            canonical, leftover = map_row_to_canonical(row_dict)
            title = canonical.get("training_title")
            if not title:
                raise ImportError_("Missing required field: Training Title")

            with transaction.atomic():
                region, local_council, jamat_khana = get_geo(
                    canonical.get("region"), canonical.get("local_council"), canonical.get("jamat_khana")
                )
                cache_key = (title, str(canonical.get("date")))
                if cache_key not in training_cache:
                    portfolio, _ = Portfolio.objects.get_or_create(name=canonical.get("portfolio") or "Training")
                    program, _ = Program.objects.get_or_create(portfolio=portfolio, name=canonical.get("program") or title)
                    training, _ = TrainingProgram.objects.get_or_create(
                        title=title,
                        date=parse_date(canonical.get("date"), field_label="Date"),
                        region=region, local_council=local_council, jamat_khana=jamat_khana,
                        defaults=dict(
                            portfolio=portfolio, program=program,
                            trainer_name=canonical.get("trainer_name", ""),
                            duration_hours=_safe_int(canonical.get("training_duration")) or 0,
                            target_audience=canonical.get("target_audience", ""),
                            created_by=user,
                        ),
                    )
                    training_cache[cache_key] = training
                else:
                    training = training_cache[cache_key]

                TrainingAttendance.objects.create(
                    training=training,
                    participant_name=canonical.get("full_name") or canonical.get("participant_name") or "Unknown",
                    cnic=canonical.get("cnic", ""),
                    contact_number=canonical.get("contact_number", ""),
                    institution_organization=canonical.get("institution_organization", ""),
                    designation_title=canonical.get("designation_title", ""),
                    attendance_status=(canonical.get("attendance_status") or "PRESENT").upper()[:10],
                    created_by=user,
                )
                training.number_of_participants = training.attendees.count()
                training.save(update_fields=["number_of_participants"])
            success += 1
        except Exception as exc:
            errors.append({"row": row_num, "error": str(exc)})
    return success, errors


def _dispatch_import(form_type, df, user):
    """Routes a dataframe to the correct import_* function for form_type."""
    if form_type == UploadBatch.FormType.ACTIVITY_REPORT:
        return import_activity_report(df, user)
    elif form_type == UploadBatch.FormType.TRAINING_ATTENDANCE:
        return import_training_attendance(df, user)
    elif form_type in SCREENING_MODELS:
        return import_screening_form(df, form_type, user)
    else:
        return 0, [{"row": 0, "error": f"Unknown form type {form_type}"}]


def process_upload_batch(batch: UploadBatch):
    """
    Entry point called by the view / management command to process a batch.

    Always processes a single sheet — the first sheet of the uploaded
    workbook for Excel files, or the only "sheet" for CSV — against the
    Form Type the uploader manually selected. Every row still goes through
    the full validation pipeline (required fields, strict date format,
    geography cross-check against existing records) exactly as before;
    only the automatic multi-tab detection has been removed.
    """
    batch.status = UploadBatch.Status.PROCESSING
    batch.save(update_fields=["status"])

    try:
        df = read_dataframe(batch.file)
    except Exception as exc:
        batch.status = UploadBatch.Status.FAILED
        batch.error_log = [{"row": 0, "error": f"Could not read file: {exc}"}]
        batch.processed_at = timezone.now()
        batch.save(update_fields=["status", "error_log", "processed_at"])
        return batch

    df = _drop_blank_rows(df)
    batch.total_rows = len(df)
    success, errors = _dispatch_import(batch.form_type, df, batch.created_by)

    batch.success_count = success
    batch.error_count = len(errors)
    batch.error_log = errors
    batch.status = (
        UploadBatch.Status.COMPLETED if not errors
        else (UploadBatch.Status.COMPLETED_WITH_ERRORS if success else UploadBatch.Status.FAILED)
    )
    batch.processed_at = timezone.now()
    batch.save(update_fields=["total_rows", "success_count", "error_count", "error_log", "status", "processed_at"])
    return batch

def build_geography_reference(user):
    """
    Live reference sheet: every Region / Local Council / Jamatkhana the
    given user has access to, pulled directly from the database at
    download time (not a static template). Bulk upload's get_geo() only
    ever matches against records that already exist, so this gives
    uploaders the exact spelling to copy into their data file instead of
    guessing and getting a row rejected.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    from core.models import LocalCouncil

    lcs = (
        LocalCouncil.objects
        .select_related("region")
        .prefetch_related("jamat_khanas")
        .order_by("region__name", "name")
    )
    if not (user.is_superuser or user.is_national):
        if user.role == user.Role.REGIONAL and user.region_id:
            lcs = lcs.filter(region_id=user.region_id)
        elif user.local_council_id:
            lcs = lcs.filter(id=user.local_council_id)
        elif user.region_id:
            lcs = lcs.filter(region_id=user.region_id)
        else:
            lcs = lcs.none()

    wb = Workbook()
    ws = wb.active
    ws.title = "Geography Reference"
    headers = ["Region", "Local Council", "Jamatkhana"]
    ws.append(headers)

    header_fill = PatternFill(start_color="0B5D63", end_color="0B5D63", fill_type="solid")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
    for i in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 30

    for lc in lcs:
        jks = list(lc.jamat_khanas.all().order_by("name"))
        if jks:
            for jk in jks:
                ws.append([lc.region.name, lc.name, jk.name])
        else:
            # Local Council with no Jamatkhanas yet - still listed, since
            # Jamatkhana is optional on most upload templates but Region /
            # Local Council are required.
            ws.append([lc.region.name, lc.name, ""])

    ws.freeze_panes = "A2"

    notes = wb.create_sheet("Notes")
    notes.column_dimensions["A"].width = 110
    notes["A1"] = "How to use this reference"
    notes["A1"].font = Font(bold=True, size=13, color="0B5D63")
    lines = [
        "",
        "This sheet lists every Region, Local Council and Jamatkhana you have access to, spelled exactly as",
        "stored in the system right now.",
        "",
        "Bulk upload cross-checks the Region / Local Council / Jamatkhana columns in your data file against",
        "these exact records and never creates new geography automatically - copy the spelling straight from",
        "here into your upload template to avoid a row being rejected for unrecognised geography.",
        "",
        "If you need a Region or Local Council that isn't listed here yet, ask a National Admin to add it via",
        "'Regions & Local Councils'. New Jamatkhanas are added via Django Admin.",
        "",
        f"Generated {timezone.now():%Y-%m-%d %H:%M} - reflects the database at the time of download, not a",
        "fixed template, so re-download this if geography has changed since your last upload.",
    ]
    for offset, line in enumerate(lines, start=2):
        notes[f"A{offset}"] = line

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf