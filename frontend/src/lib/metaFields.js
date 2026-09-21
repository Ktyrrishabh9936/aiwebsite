export const META_FIELDS = [
  ["meta_lead_id", "Meta Lead ID"], ["meta_created_time", "Meta Lead Created Time"],
  ["meta_campaign_name", "Meta Campaign Name"], ["meta_campaign_id", "Meta Campaign ID"],
  ["meta_adset_name", "Meta Ad Set Name"], ["meta_adset_id", "Meta Ad Set ID"],
  ["meta_ad_name", "Meta Ad Name"], ["meta_ad_id", "Meta Ad ID"],
  ["meta_form_name", "Meta Form Name"], ["meta_form_id", "Meta Form ID"],
  ["meta_platform", "Meta Platform"], ["meta_is_organic", "Meta Is Organic"],
];

export const SHEET_MAPPING_FIELDS = [
  ...META_FIELDS.map(([key, label]) => ({ key, label })),
  { key: "status", label: "CRM Status (write-back)" },
];
