"""Versioned relation instructions, not a category vocabulary.

v3 corrects exposed development failures (never final-test tuning): payment
periods, coarse/fine abstraction, and Ukrainian abbreviations misread as wages.
Terminology sources (definitions only; no tax rates or legal advice):
https://www.tax.gov.ua/nk/rozdil-iv--podatok-na-dohodi-fizichnih-o/
https://tax.gov.ua/zakonodavstvo/elektronni-formi-dokumentiv/podatok-na-dohodi-fizichnih-osib/
https://www.tax.gov.ua/deklaratsiyna-kampaniya-2026/stavki-podatku-na-dohodi-fizichnih-osib-ta-viyskovogo-zboru
"""
from .local_teacher import SYSTEM, PROMPT_VERSION

CLARIFICATIONS = """
Important interpretation rules for BOTH levels:
- Reporting month, year, due date, amount, document number and counterpart identity alone NEVER make different economic categories.
- Decide coarse FIRST. A possible difference in a narrower fine subtype must NOT override a known common coarse obligation.
- An unspecified narrower detail is not evidence of a different obligation. Use fine uncertain if needed, while retaining an evidenced coarse same.
- Different kinds of purchased physical goods can share a procurement obligation at coarse level; fine can distinguish their economic object. Do not infer fixed asset vs resale, capital vs operating use without explicit support.
- A transfer of an organization's money to its other account is internal movement, just like a transfer between its own accounts. Do not invent an external beneficiary.
- Repayment of a loan and repayment of borrowed funds share debt servicing at coarse level. Lack of a principal/interest breakdown alone does not prove coarse different.
- Separate the actual recipient/obligation from the BASE used to calculate payment. A tax or contribution ON salary/vacation pay is not the salary/vacation pay paid to an employee.
- Different explicitly named taxes or statutory contributions may share a broader budget-payment obligation, but are NOT the same fine obligation merely because both concern payroll.
Ukrainian terminology aid, NOT an output category list:
ПДФО / пдфо = податок на доходи фізичних осіб = personal income tax.
ЄСВ / єсв = єдиний соціальний внесок / єдиний внесок на загальнообов'язкове державне соціальне страхування = unified social insurance contribution.
військовий збір = military levy; distinct from both personal income tax and the social insurance contribution.
відпускні = vacation pay; лікарняні = sick-leave payments. A deduction or contribution calculated on them is its own obligation, not the employee payment itself.
Do not guess an unfamiliar abbreviation. If its economic object/role cannot be established, use uncertain.
Evidence must be COPIED literally, not lemmatized or translated. Prefer one short economic term copied exactly over a grammatically modified phrase. No generic payment words or numbers as the only economic evidence.
The rationale must accurately describe BOTH source objects; a matching relation with invented objects is still a bad proposal.
Return the same five JSON fields only: coarse, fine, left_evidence, right_evidence, rationale.
"""


def policy(name):
    if name == "v2":
        return SYSTEM, PROMPT_VERSION
    if name == "v3":
        return SYSTEM+CLARIFICATIONS, "economic_relations_grounded_v3"
    raise ValueError("unknown relation policy")
