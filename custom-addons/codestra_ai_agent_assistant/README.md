# Codestra AI Agent Assistant

Stores bounded, reviewable AI outputs for interaction summaries, knowledge suggestions, and draft responses. Requests retain hashes and controlled record references rather than raw provider prompts. Generation is recorded by an authorized service role, and approval requires a different human reviewer.

The model deliberately has no send action and no field or method for consent, DNC, refunds, disposition finalization, provider delivery, or customer-record mutation. Approval means only “approved as a draft”; a separately authorized human workflow must perform any business action.
