"""Source attribution and mapping metadata, separate from editable CRM fields."""
import re


def strip_meta_phone_prefix(value):
    """Remove Meta's `p:` phone marker while retaining the country-code plus sign."""
    if not isinstance(value, str):
        return value
    return re.sub(r"^p\s*:\s*(?=\+?\d)", "", value.strip(), count=1, flags=re.IGNORECASE)


META_FIELDS = {
    "meta_lead_id": ("id", "Meta Lead ID"),
    "meta_created_time": ("created_time", "Meta Lead Created Time"),
    "meta_ad_id": ("ad_id", "Meta Ad ID"),
    "meta_ad_name": ("ad_name", "Meta Ad Name"),
    "meta_adset_id": ("adset_id", "Meta Ad Set ID"),
    "meta_adset_name": ("adset_name", "Meta Ad Set Name"),
    "meta_campaign_id": ("campaign_id", "Meta Campaign ID"),
    "meta_campaign_name": ("campaign_name", "Meta Campaign Name"),
    "meta_form_id": ("form_id", "Meta Form ID"),
    "meta_form_name": ("form_name", "Meta Form Name"),
    "meta_is_organic": ("is_organic", "Meta Is Organic"),
    "meta_platform": ("platform", "Meta Platform"),
}


def header_index(headers, name):
    matches = [i for i, h in enumerate(headers) if str(h).strip().casefold() == str(name).strip().casefold()]
    if len(matches) != 1:
        raise ValueError("Mapped Sheet header is missing or ambiguous. Refresh and save the mapping.")
    return matches[0]


def map_sheet_row(headers, row, column_map, field_keys):
    values, attribution = {}, {}
    for key, header in column_map.items():
        if not header or key not in set(field_keys) | set(META_FIELDS):
            continue
        index = header_index(headers, header)
        value = row[index] if index < len(row) else ""
        if key in META_FIELDS:
            if key == "meta_is_organic":
                value = {"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False}.get(str(value).strip().lower())
            else:
                value = str(value).strip() if value is not None else None
            attribution[key] = value
        else:
            values[key] = strip_meta_phone_prefix(value) if key == "phone" else value
    return values, attribution


def pending_sheet_sync(lead, status):
    if lead.get("status", "new") == status or not (lead.get("google_sheet_spreadsheet_id") or lead.get("source") == "google_sheet"):
        return {}
    return {"google_sheet_sync_status": "pending", "google_sheet_sync_error": None,
            "google_sheet_sync_next_attempt_at": None}
