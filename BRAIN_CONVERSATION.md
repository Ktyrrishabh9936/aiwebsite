# Brain conversation

Company knowledge now opens with a guided chat. The Brain coach asks about missing business profile, organisation, brand, audience, goals, evidence and decision-memory topics. The workspace model polishes answers into the existing Brain structure. Optional topics can be skipped and any draft topic can be revised through chat. Unclear answers request clarification; failed model requests preserve the draft and typed answer.

The authenticated `/workspaces/{ws_id}/brain/conversation` GET and POST endpoints save conversation history and owner-supplied patches with optimistic revisions. Drafts do not change active company knowledge. Completion uses `/brain/conversation/complete`, verifies the revision and current Brain, and publishes the reviewed knowledge with `brain_status=ready`. Website training must finish before completion to prevent conflicting updates. Crawl metadata, unknown Brain fields and existing organisation document settings are preserved. Unedited facts can still be refreshed by website training.

The existing editor, JSON editing and website retraining remain under **Advanced knowledge editor and website training**. Both frontend and Lambda backend must be redeployed to enable chat. Existing Sales Strategy chat remains available in the Sales strategy tab.

Tests cover structured-answer validation, draft persistence, stale revisions, optional evidence, readable previews, completion, and preserving crawl metadata and invoice settings.
