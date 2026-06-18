import json, base64, csv, io, re, xml.etree.ElementTree as ET
from datetime import date

JSON_PATH = "/root/.claude/projects/-home-user-TelegramBot-OpenAI-API/a6fc4438-5d62-5458-b64b-8f2c845d451a/tool-results/mcp-Google_Drive-download_file_content-1781741751180.txt"
XML_PATH = "/root/.claude/uploads/a6fc4438-5d62-5458-b64b-8f2c845d451a/12469e70-NL57INGB0107226480_01062025_17062026_1.xml"

# ---------- load invoices ----------
with open(JSON_PATH) as f:
    data = json.load(f)
csv_bytes = base64.b64decode(data["content"])
text = csv_bytes.decode("utf-8")
reader = csv.reader(io.StringIO(text))
rows = list(reader)
header = rows[0]
invoices = [r for r in rows[1:] if len(r) >= 18 and any(c.strip() for c in r)]

# columns
# 0 Leverancier,1 Factuurnummer,2 excl,3 btw%,4 btwbedrag,5 Totaal incl,6 Factuurdatum,
# 7 termijn,8 Vervaldatum,9 Categorie,10 Bestandsnaam,11 FileID,12 Verwerkingsdatum,
# 13 Betaald,14 HerinnerMoment,15 Herinnering verstuurd,16 Email herinnering verstuurd,17 Email datum

def parse_amount(s):
    """Parse verbatim NL/US amount string to float. Returns None if blank."""
    s = s.strip().replace("€", "").replace("EUR", "").strip()
    if s == "":
        return None
    s = s.replace(" ", "")
    # if both . and , -> . thousands, , decimal
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

from datetime import timedelta
def parse_date(s):
    s = s.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # Excel serial date (1899-12-30 epoch)
    if re.fullmatch(r"\d{4,6}", s):
        try:
            return date(1899, 12, 30) + timedelta(days=int(s))
        except (ValueError, OverflowError):
            return None
    return None

def norm(s):
    return re.sub(r"\s+", "", s.upper())

def token_in(invnum, ustrd):
    """Match invoice number as contiguous token, allowing separators , / - space around it."""
    inv = norm(invnum)
    if not inv:
        return False
    u = ustrd.upper()
    # find all maximal alnum-ish tokens split by separators , / - and whitespace
    # we want inv to appear as a standalone token (delimited by start/end or sep)
    # build regex: (?<![A-Z0-9])INV(?![A-Z0-9]) but inv may contain - which we stripped.
    # Normalize ustrd by removing spaces too, then split on , / - and check tokens,
    # AND also check the space-free contiguous form.
    # Approach: tokenize ustrd on [\s,/]+ then for each token strip surrounding '-'?
    # invoice numbers themselves can contain '-'. So treat '-' as part of token.
    tokens = re.split(r"[\s,/]+", u)
    for t in tokens:
        if norm(t) == inv:
            return True
    # also handle space-removed contiguous: e.g. "PB 0000.2503" -> norm
    if inv in norm(u):
        # require delimiter boundaries in the space-removed string
        un = norm(u)
        # boundary chars: anything not alnum
        for m in re.finditer(re.escape(inv), un):
            a = m.start()-1
            b = m.end()
            left = un[a] if a >= 0 else ""
            right = un[b] if b < len(un) else ""
            if (not left.isalnum()) and (not right.isalnum()):
                return True
    return False

# ---------- parse XML ----------
NS = {"d": "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"}
tree = ET.parse(XML_PATH)
root = tree.getroot()

# Build list of debit transactions. Each TxDtls -> creditor + ustrd, with entry booking date & entry amount.
txns = []  # dict: bookdate, entry_amt, entry_cdtdbt, cdtr_name, cdtr_iban, ustrd
for ntry in root.iter("{urn:iso:std:iso:20022:tech:xsd:camt.053.001.02}Ntry"):
    def g(path):
        e = ntry.find(path, NS)
        return e.text if e is not None else None
    cdtdbt = g("d:CdtDbtInd")
    entry_amt = g("d:Amt")
    bd = ntry.find("d:BookgDt/d:Dt", NS)
    bookdate = bd.text if bd is not None else None
    if cdtdbt != "DBIT":
        continue
    txdetails = ntry.findall("d:NtryDtls/d:TxDtls", NS)
    if not txdetails:
        continue
    # collect all creditor names in this entry (for bulk cross-checking)
    entry_cdtrs = []
    for tx in txdetails:
        n = tx.find("d:RltdPties/d:Cdtr/d:Nm", NS)
        if n is not None and n.text:
            entry_cdtrs.append(n.text)
    for tx in txdetails:
        cdtr_nm = tx.find("d:RltdPties/d:Cdtr/d:Nm", NS)
        cdtr_iban = tx.find("d:RltdPties/d:CdtrAcct/d:Id/d:IBAN", NS)
        ustrds = [u.text or "" for u in tx.findall("d:RmtInf/d:Ustrd", NS)]
        tx_amt = tx.find("d:Amt", NS)
        txns.append({
            "bookdate": bookdate,
            "bookdate_d": parse_date(bookdate) if bookdate else None,
            "entry_amt": entry_amt,
            "tx_amt": tx_amt.text if tx_amt is not None else None,
            "cdtr_name": cdtr_nm.text if cdtr_nm is not None else "",
            "cdtr_iban": cdtr_iban.text if cdtr_iban is not None else "",
            "ustrd": " ".join(ustrds),
            "is_bulk": len(txdetails) > 1,
            "entry_cdtrs": entry_cdtrs,
        })

def name_similar(supplier, cdtr):
    s = norm(supplier)
    c = norm(cdtr)
    if not c:
        return False
    # strip common suffixes
    def core(x):
        x = re.sub(r"(B\.?V\.?|N\.?V\.?|GMBH|LIMITED|LTD)$", "", x)
        return x
    sc, cc = core(s), core(c)
    if not sc or not cc:
        return s in c or c in s
    # significant overlap: one contains a 4+ char prefix of the other's first word
    if sc in cc or cc in sc:
        return True
    # compare first word
    sw = re.split(r"[^A-Z0-9]+", supplier.upper())
    cw = re.split(r"[^A-Z0-9]+", cdtr.upper())
    sw = [w for w in sw if len(w) >= 4]
    cw = [w for w in cw if len(w) >= 4]
    for w in sw:
        if w in cw:
            return True
    return False

zeker = []
twijfel = []
amount_name_only = 0

for inv in invoices:
    leverancier = inv[0].strip()
    factnum = inv[1].strip()
    totaal = inv[5].strip()
    factdatum = inv[6].strip()
    betaald = inv[13].strip()
    fileid = inv[11].strip()
    if betaald.lower() != "nee":
        continue
    if "stone member" in leverancier.lower():
        continue
    amt = parse_amount(totaal)
    if amt is None or amt <= 0:
        continue
    fdate = parse_date(factdatum)

    # find matching txns by invoice number token
    matches = [t for t in txns if factnum and token_in(factnum, t["ustrd"])]
    if not matches:
        continue

    # pick best match; prefer ones with name match & date ok
    chosen = None
    chosen_level = None
    chosen_reason = None
    for t in matches:
        date_ok = (t["bookdate_d"] is not None and fdate is not None and t["bookdate_d"] >= fdate)
        # name ok if direct creditor matches OR (bulk) supplier appears as any creditor in entry
        name_ok = name_similar(leverancier, t["cdtr_name"]) or \
                  any(name_similar(leverancier, c) for c in t.get("entry_cdtrs", []))
        if date_ok and name_ok:
            chosen, chosen_level, chosen_reason = t, "ZEKER", None
            break
    if chosen is None:
        # twijfel: take a match, determine reason
        for t in matches:
            name_ok = name_similar(leverancier, t["cdtr_name"]) or \
                      any(name_similar(leverancier, c) for c in t.get("entry_cdtrs", []))
            if name_ok:  # name matches but date failed
                if fdate is None:
                    reason = "factuurdatum onleesbaar; boekdatum-controle niet mogelijk"
                else:
                    reason = "boekdatum < factuurdatum (mogelijk nummer-hergebruik/toeval)"
                chosen, chosen_level, chosen_reason = t, "TWIJFEL", reason
                break
        if chosen is None:
            t = matches[0]
            chosen, chosen_level = t, "TWIJFEL"
            chosen_reason = "creditor-naam wijkt af van leverancier"

    rec = {
        "bookdate": chosen["bookdate"],
        "leverancier": leverancier,
        "factnum": factnum,
        "totaal": totaal,
        "cdtr": chosen["cdtr_name"],
        "bankamt": (chosen["tx_amt"] or chosen["entry_amt"]) + (" (bulk-totaal)" if chosen["is_bulk"] else ""),
        "ustrd": chosen["ustrd"][:90],
        "fileid": fileid,
        "reason": chosen_reason,
        "amt": amt,
    }
    if chosen_level == "ZEKER":
        zeker.append(rec)
    else:
        twijfel.append(rec)

zeker.sort(key=lambda r: r["bookdate"] or "")
twijfel.sort(key=lambda r: r["bookdate"] or "")

def out_table(recs, with_reason=False):
    for r in recs:
        cols = [r["bookdate"], r["leverancier"], r["factnum"], r["totaal"], r["cdtr"],
                r["bankamt"], r["ustrd"], r["fileid"]]
        if with_reason:
            cols.append(r["reason"])
        print(" | ".join(str(c) for c in cols))

print("=== TABEL 1: ZEKER betaald (aftikken) ===")
out_table(zeker)
print()
print("=== TABEL 2: TWIJFEL (handmatig checken) ===")
out_table(twijfel, with_reason=True)
print()
print(f"Aantal ZEKER: {len(zeker)}")
print(f"Aantal TWIJFEL: {len(twijfel)}")
total = sum(r["amt"] for r in zeker)
print(f"Som-totaal TABEL 1 (Totaal incl BTW): {total:.2f}")
print(f"DBIT TxDtls totaal in afschrift: {len(txns)}")
