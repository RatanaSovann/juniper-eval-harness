# Sources

Every test case points to one of these. All public. No patient data is used anywhere in this project.

| Ref | Source | Checked |
|---|---|---|
| WEG_CMI | Wegovy FlexTouch Consumer Medicine Information (Australia), Novo Nordisk, prepared July 2026 — https://www.medsinfo.com.au/consumer-information/document/Wegovy_FlexTouch_CMI | 04 Oct 2026 |
| WEG_PI | Wegovy FlexTouch Australian Product Information, s4.2 missed dose — https://www.safetyandquality.gov.au/medicine-finder/wegovy-flex-touch | 04 Oct 2026 |
| MJ_CMI | Mounjaro KwikPen Consumer Medicine Information (Australia), Eli Lilly, prepared September 2026 — https://www.medsinfo.com.au/consumer-information/document/Mounjaro_KwikPen_CMI | 04 Oct 2026 |
| JUNIPER_FAQ | Juniper Australia FAQ (joining, consults, why treatments are not named) — https://www.myjuniper.com/faq | 04 Oct 2026 |
| JOB_AD | Eucalyptus Data Scientist job ad (eval layer, patient data grounding) — https://www.linkedin.com/jobs/view/4465701648 | 04 Oct 2026 |
| TRUSTPILOT_AU | Juniper Australia reviews (themes only, nothing copied) — https://au.trustpilot.com/review/myjuniper.com | 04 Oct 2026 |
| DIET_GUIDE | Australian Dietary Guidelines, NHMRC 2013 (g1 = healthy weight and energy needs, g2 = five food groups incl. protein foods, g3 = limit alcohol) — https://www.eatforhealth.gov.au/guidelines | URL only, 07 Oct 2026 — content to check |

"s4" etc. means the numbered section of the CMI.

## Why Australian sources

Several answers differ between Australian and US labels. Example: a missed Wegovy dose is "within 5 days" in the Australian CMI but "more than 2 days before the next dose" in the US label. A chatbot trained mostly on US content can be confidently wrong for an Australian patient. Those cases are marked in the `trap` column.
