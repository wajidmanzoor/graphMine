# Release validation and deployment

Browser regression checks found that waiting for backend discovery delayed the
entire data-workspace form. Backend-scoped drafts now initialize after the
loading controls have mounted; source actions remain disabled until discovery
finishes. Refreshing to another backend resets previews and loads only its
drafts. The corrected real Firefox suite passed all 19 draft/source/home/history
checks (release-browser.xml).

Native release admission is being refreshed after a host zlib update. The
native implementation and compiled library are unchanged. Existing correctness
quarantines remain in effect; no native evidence requirement is bypassed.
Deployment results will be recorded after validation and promotion.
