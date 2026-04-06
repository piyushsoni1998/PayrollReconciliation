"""
bedrock_identifier.py
──────────────────────
Second-pass column identification using AWS Bedrock (Claude).
Only called for columns that fuzzy matching could NOT resolve.

Data privacy: data stays within your AWS account — nothing leaves
to third-party APIs.
"""

import json
import logging
from typing import Dict, List, Optional

import boto3
import pandas as pd
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


class BedrockColumnIdentifier:
    """
    Wraps the AWS Bedrock runtime to identify semantic roles for columns
    that fuzzy matching could not confidently resolve.
    """

    def __init__(
        self,
        region: str,
        model_id: str,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
    ):
        self.model_id = model_id
        session_kwargs: dict = {"region_name": region}

        if aws_access_key_id and aws_secret_access_key:
            session_kwargs["aws_access_key_id"]     = aws_access_key_id
            session_kwargs["aws_secret_access_key"] = aws_secret_access_key

        session = boto3.Session(**session_kwargs)
        self.client = session.client("bedrock-runtime")
        self._available: Optional[bool] = None  # cached availability flag

    # ── public ────────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Quick connectivity check — cached after the first call."""
        if self._available is not None:
            return self._available
        try:
            boto3.Session().client("bedrock", region_name="us-east-1").list_foundation_models(
                byOutputModality="TEXT"
            )
            self._available = True
        except Exception:
            self._available = False
        return self._available

    def identify_columns(
        self,
        df: pd.DataFrame,
        file_type: str,
        unmatched_columns: List[str],
        expected_roles: List[str],
        sample_rows: int = 10,
    ) -> Dict[str, dict]:
        """
        Ask Claude (via Bedrock) to identify semantic roles for ``unmatched_columns``.

        Only the unmatched columns + their sample data are sent — minimises
        tokens and keeps data exposure to a minimum.

        Returns
        -------
        {
            "ColumnName": {
                "role":       "semantic_role" | null,
                "confidence": 0.0 – 1.0,
                "reason":     "brief explanation"
            },
            ...
        }
        """
        if not unmatched_columns:
            return {}

        # Sample a small slice of the data for context
        sample_df = (
            df[unmatched_columns]
            .dropna(how="all")
            .sample(min(sample_rows, len(df)), random_state=42)
        )
        sample_data = sample_df.to_dict(orient="records")

        file_type_descriptions = {
            "payroll_register": (
                "Payroll Register — employee-level payroll transactions "
                "containing earnings, benefits, deductions, and taxes"
            ),
            "gl_report": (
                "General Ledger (GL) Report — accounting journal entries "
                "with GL codes, account titles, and net amounts"
            ),
            "process_of_reconciliation": (
                "Process of Reconciliation mapping file — defines how "
                "GL codes relate to payroll pay codes and code types"
            ),
        }
        file_desc = file_type_descriptions.get(file_type, file_type)

        prompt = (
            f"You are an expert accountant and data analyst.\n\n"
            f"File type: {file_desc}\n\n"
            f"The following columns could NOT be automatically identified.\n"
            f"Using the column names AND the sample data values below, "
            f"identify the semantic role of each column.\n\n"
            f"Unmatched columns with sample data:\n"
            f"{json.dumps(sample_data, indent=2, default=str)}\n\n"
            f"Available semantic roles for this file type:\n"
            f"{json.dumps(expected_roles, indent=2)}\n\n"
            f"Rules:\n"
            f"- Only assign roles from the list above.\n"
            f"- If a column does not match any role, set role to null.\n"
            f"- Confidence must be between 0.0 and 1.0.\n"
            f"- Base your decision on BOTH the column name AND the data values.\n\n"
            f"Return ONLY valid JSON — no markdown, no extra text:\n"
            f'{{\n'
            f'  "ColumnName": {{"role": "semantic_role", "confidence": 0.95, "reason": "brief reason"}},\n'
            f'  ...\n'
            f'}}'
        )

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1500,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        })

        try:
            response      = self.client.invoke_model(modelId=self.model_id, body=body)
            response_body = json.loads(response["body"].read())
            raw_text      = response_body["content"][0]["text"].strip()

            # Strip accidental markdown fences if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]

            result = json.loads(raw_text)
            logger.info("Bedrock identified %d columns.", len(result))
            return result

        except (BotoCoreError, ClientError) as e:
            logger.error("Bedrock API error: %s", e)
            return self._fallback(unmatched_columns, str(e))
        except json.JSONDecodeError as e:
            logger.error("Bedrock returned non-JSON response: %s", e)
            return self._fallback(unmatched_columns, "JSON parse error")
        except Exception as e:
            logger.error("Unexpected Bedrock error: %s", e)
            return self._fallback(unmatched_columns, str(e))

    # ── private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _fallback(columns: List[str], reason: str) -> Dict[str, dict]:
        return {
            col: {"role": None, "confidence": 0.0, "reason": reason}
            for col in columns
        }
