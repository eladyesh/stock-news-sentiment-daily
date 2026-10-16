"""Resolve explicit symbols and conservative issuer-name matches."""
from __future__ import annotations

from collections import defaultdict
import csv
import io
import re

from .core import clean, words

DIRECTORIES = [
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
]
COMMON_NAMES = {"global", "general", "first", "united", "national", "american", "international",
                "western", "eastern", "southern", "central", "bank", "financial", "new", "capital"}
AMBIGUOUS_SINGLE_NAMES = COMMON_NAMES | {"nasdaq", "universal", "pearson", "progress", "harmony",
                                      "context", "shift", "rocket", "toast", "vertex", "monday"}
COMPANY_CUES = {"inc", "incorporated", "corp", "corporation", "plc", "ltd", "limited", "holdings",
               "stock", "stocks", "shares", "earnings", "revenue", "guidance", "forecast", "outlook",
               "profit", "profits", "margins", "reports", "reported", "announces", "announced",
               "acquires", "launches", "raises", "cuts", "buyback", "repurchase", "upgrade", "downgrade"}


def parse_directory(text: str) -> dict[str, str]:
    securities = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="|"):
        ticker = row.get("Symbol") or row.get("ACT Symbol")
        name = row.get("Security Name", "")
        if not ticker or not name or row.get("Test Issue") == "Y" or row.get("ETF") == "Y":
            continue
        if re.search(r"\b(warrants?|preferred|units?|rights|notes|debentures)\b", name, re.I):
            continue
        if re.fullmatch(r"[A-Z]{1,5}(?:[.\-][A-Z])?", ticker):
            securities[ticker.replace("-", ".")] = name
    return securities


def fetch_universe(client) -> dict[str, str]:
    securities = {}
    # A failure is explicit: do not silently call a partial directory the whole universe.
    for url in DIRECTORIES:
        securities.update(parse_directory(client.get(url)[0].decode("utf-8")))
    if len(securities) < 1000:
        raise ValueError("Incomplete US listing directory")
    return securities


def issuer_name(name: str) -> str:
    name = re.split(r"\s+-\s+", name)[0]
    name = re.sub(r"\b(Common (Stock|Shares)|Ordinary Shares|Class [A-Z]|American Depositary.*)$", "", name, flags=re.I)
    name = re.sub(r"\b(Inc\.?|Corporation|Corp\.?|Limited|Ltd\.?|plc|S\.A\.)$", "", name.strip(), flags=re.I)
    return clean(name).strip(" ,.-")


class Resolver:
    def __init__(self, securities: dict[str, str]):
        self.names = {k: issuer_name(v) for k, v in securities.items()}
        self.by_first: dict[str, list[tuple[list[str], str]]] = defaultdict(list)
        for ticker, name in self.names.items():
            alias = words(name)
            if not alias:
                continue
            if len(alias) > 1 or (len(alias[0]) >= 5 and alias[0] not in AMBIGUOUS_SINGLE_NAMES):
                self.by_first[alias[0]].append((alias, ticker))
            # Preserve full legal forms for ambiguous single-word issuers (Nasdaq, Inc.).
            legal = words(re.split(r"\s+-\s+", securities[ticker])[0])
            if len(alias) == 1 and len(legal) > 1 and legal[1] in COMPANY_CUES:
                self.by_first[legal[0]].append((legal, ticker))

    def resolve(self, text: str) -> list[str]:
        explicit = re.findall(r"(?:\$|\b(?:NASDAQ|NYSE|AMEX|NYSEAMERICAN)\s*:\s*)([A-Z]{1,5}(?:[.\-][A-Z])?)\b", text, re.I)
        found = {x.upper().replace("-", ".") for x in explicit if x.upper().replace("-", ".") in self.names}
        tokens = words(text)
        for pos, token in enumerate(tokens):
            for alias, ticker in self.by_first.get(token, []):
                if tokens[pos:pos + len(alias)] == alias:
                    if len(alias) == 1:
                        following = tokens[pos + 1:pos + 3]
                        if following and following[0] == "s":
                            following = following[1:]
                        if not following or (following[0] not in COMPANY_CUES and following[0].upper() != ticker):
                            continue
                    found.add(ticker)
        # Bare short words (BE, ON, IT, AI) and uppercase financial jargon are never symbols alone.
        return sorted(found)
