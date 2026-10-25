"""Conservative M6 output hints, separate from learned native category IDs.

These text rules are not training targets, model confidence, or the discovered
taxonomy. Missing evidence leaves `other`; M6 can still inspect original text.
"""
import re
from .relation_guard import obligation_evidence


def hint(purpose,direction):
    text=purpose.casefold().replace('ё','е');tags,employee=obligation_evidence(text)
    if re.search(r'между\s+(?:своими|собственн\w*)\s+(?:расчетн\w*\s+)?счет',text):return 'own_transfer'
    loan=bool(re.search(r'\b(?:займ\w*|заем\w*|кредит\w*|ссуд\w*)',text))
    if loan and re.search(r'учредител|участник|собственник|владельц',text):return 'owner_loan'
    if loan:return 'loan_payment'
    if direction=='in':
        if re.search(r'возврат|повернен',text):return 'refund'
        if re.search(r'выручк|виручк|за реализован|за продан|за поставк',text):return 'revenue_b2b'
        return 'other'
    if tags or re.search(r'уплата\s+налог|перечисление\s+налог|сплата\s+подат',text):return 'tax'
    if re.search(r'фссп|исполнительн\w*\s+(?:лист|производств)|виконавч\w*\s+(?:лист|проваджен)',text):return 'enforcement'
    if employee:return 'salary'
    if re.search(r'лизинг|лізинг',text):return 'leasing'
    if re.search(r'аренд|оренд',text):return 'rent'
    if re.search(r'коммунальн|комунальн|электроэнерг|електроенерг',text):return 'utilities'
    if re.search(r'\bрко\b|комисси\w*\s+банк|коміс\w*\s+банк|банковск\w*\s+комис',text):return 'bank_fee'
    if re.search(r'реклам|маркетинг|просуван',text):return 'marketing'
    if re.search(r'услуг|послуг',text):return 'services'
    if re.search(r'товар|за поставк|приобрет|покупк|закуп',text):return 'supplier'
    return 'other'
