import hashlib
import json
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class ColumnRule(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["string", "integer", "number", "date"] = "string"
    required: bool = True
    non_null: bool = True
    minimum: float | None = None
    maximum: float | None = None
    allowed: list[str] = Field(default_factory=list, max_length=100)
    date_format: str = "%Y-%m-%d"

    @model_validator(mode="after")
    def bounds(self):
        if self.minimum is not None and not math.isfinite(self.minimum):
            raise ValueError("Minimum must be finite")
        if self.maximum is not None and not math.isfinite(self.maximum):
            raise ValueError("Maximum must be finite")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("Minimum exceeds maximum")
        return self


class Rules(BaseModel):
    columns: list[ColumnRule] = Field(min_length=1, max_length=100)
    unique_keys: list[str] = Field(min_length=1, max_length=10)
    unexpected: Literal["reject", "warn", "allow"] = "warn"
    max_failure_rate: float = Field(default=0.25, ge=0, le=1)

    @model_validator(mode="after")
    def keys(self):
        names = [c.name for c in self.columns]
        if len(set(names)) != len(names):
            raise ValueError("Column names must be unique")
        if not set(self.unique_keys).issubset(names):
            raise ValueError("Unique keys must be configured columns")
        if any(
            not c.non_null or not c.required
            for c in self.columns
            if c.name in self.unique_keys
        ):
            raise ValueError("Unique keys must be required and non-null")
        return self


SALES = Rules(
    columns=[
        ColumnRule(name="transaction_id"),
        ColumnRule(name="customer_id"),
        ColumnRule(name="transaction_date", type="date"),
        ColumnRule(name="amount", type="number", minimum=0, maximum=1000000),
        ColumnRule(name="currency", allowed=["USD", "EUR", "GBP"]),
        ColumnRule(name="region", allowed=["North", "South", "East", "West"]),
    ],
    unique_keys=["transaction_id"],
).model_dump()


def issue(rule, field, message):
    return {"rule": rule, "field": field, "message": message}


def dataset_issues(columns, rules):
    failures = [
        issue("required_column", c["name"], "Required column is missing")
        for c in rules["columns"]
        if c["required"] and c["name"] not in columns
    ]
    extra = sorted(set(columns) - {c["name"] for c in rules["columns"]})
    warnings = []
    if extra and rules["unexpected"] != "allow":
        target = failures if rules["unexpected"] == "reject" else warnings
        target.append(
            issue(
                "unexpected_column",
                ", ".join(extra),
                "Unexpected columns: " + ", ".join(extra),
            )
        )
    return failures, warnings


def validate(values, rules):
    # Trim strings; blank means null. No coercion of malformed numbers/dates.
    result, failures = {}, []
    for c in rules["columns"]:
        name = c["name"]
        raw = values.get(name)
        value = str(raw).strip() if raw is not None else ""
        if not value:
            result[name] = None
            if c["non_null"]:
                failures.append(issue("non_null", name, "A value is required"))
            continue
        parsed = value
        try:
            if c["type"] in ("number", "integer"):
                num = Decimal(value)
                if not num.is_finite():
                    raise ValueError()
                if c["type"] == "integer" and num != num.to_integral_value():
                    raise ValueError()
                if c["minimum"] is not None and num < Decimal(str(c["minimum"])):
                    failures.append(
                        issue("minimum", name, f"Must be at least {c['minimum']}")
                    )
                if c["maximum"] is not None and num > Decimal(str(c["maximum"])):
                    failures.append(
                        issue("maximum", name, f"Must be at most {c['maximum']}")
                    )
                # Store decimal text to avoid binary floating-point loss.
                parsed = int(num) if c["type"] == "integer" else format(num, "f")
            elif c["type"] == "date":
                parsed = datetime.strptime(value, c["date_format"]).date().isoformat()
        except (ValueError, InvalidOperation, OverflowError):
            failures.append(issue("type", name, f"Expected {c['type']}"))
            parsed = None
        if c["allowed"] and value not in c["allowed"]:
            failures.append(
                issue("allowed", name, "Allowed: " + ", ".join(c["allowed"]))
            )
        result[name] = parsed
    return result, failures


def business_key(values, rules):
    return hashlib.sha256(
        json.dumps(
            [values[k] for k in rules["unique_keys"]], separators=(",", ":")
        ).encode()
    ).hexdigest()
