"""
CrewAI crew for automated chargeback dispute.

Pipeline:
  1. DataAgent      — pulls transaction + customer history from TiDB
  2. EnrichmentAgent — enriches IP address via Skyfire-paid geolocation API
  3. AnalystAgent   — analyzes evidence and drafts the dispute narrative
  4. CoordinatorAgent — compiles final structured evidence package for PDF generation
"""
import json
import os
from dataclasses import dataclass

from crewai import LLM, Agent, Crew, Process, Task
from dotenv import load_dotenv

from agents.tools import (
    FetchCustomerHistoryTool,
    FetchIpTransactionsTool,
    FetchTransactionTool,
    IpEnrichmentTool,
)

load_dotenv()


@dataclass
class DisputeEvidence:
    transaction: dict
    chargeback: dict
    customer_history: dict
    ip_enrichment: dict
    ip_transactions: list
    narrative: str


def run_dispute_crew(chargeback_id: str, transaction_id: str, chargeback_meta: dict) -> DisputeEvidence:
    """
    Orchestrate all agents and return a structured DisputeEvidence object
    ready to be rendered into a PDF.
    """
    llm = LLM(
        model="openai/openai/gpt-oss-120b",  # LiteLLM strips the first 'openai/' (provider prefix); Groq receives 'openai/gpt-oss-120b'
        api_key=os.environ["GROQ_API_KEY"],
        api_base="https://api.groq.com/openai/v1",
    )

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------
    data_agent = Agent(
        role="Transaction Data Specialist",
        goal="Retrieve complete transaction and customer history data from the database",
        backstory=(
            "You are an expert at querying merchant databases to gather comprehensive "
            "transaction evidence. You fetch every relevant data point: IP addresses, "
            "purchase history, billing details, and account events."
        ),
        tools=[FetchTransactionTool(), FetchCustomerHistoryTool()],
        llm=llm,
        verbose=True,
    )

    enrichment_agent = Agent(
        role="IP Intelligence Analyst",
        goal="Enrich IP address data and cross-reference it against all known transactions",
        backstory=(
            "You specialize in IP address intelligence. You determine geolocation, ISP, "
            "and risk signals for any IP involved in a dispute, and find all transactions "
            "that share the same IP to demonstrate consistent legitimate usage."
        ),
        tools=[IpEnrichmentTool(), FetchIpTransactionsTool()],
        llm=llm,
        verbose=True,
    )

    analyst_agent = Agent(
        role="Chargeback Dispute Analyst",
        goal="Analyze all evidence and write a compelling, professional dispute narrative",
        backstory=(
            "You are a seasoned payments risk analyst who has written hundreds of successful "
            "chargeback dispute responses. You know exactly what card networks (Visa, Mastercard) "
            "look for in a winning dispute: consistent IP usage, purchase history, matching billing "
            "details, and a clear timeline. You write concisely and persuasively."
        ),
        tools=[],
        llm=llm,
        verbose=True,
    )

    coordinator_agent = Agent(
        role="Evidence Package Coordinator",
        goal="Compile all gathered evidence into a clean, structured JSON package",
        backstory=(
            "You are responsible for assembling the final dispute evidence package. "
            "You organize data from all other agents into a structured format that "
            "can be rendered into a professional PDF document."
        ),
        tools=[],
        llm=llm,
        verbose=True,
    )

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------
    task_fetch_data = Task(
        description=(
            f"Fetch the transaction record for transaction_id='{transaction_id}'. "
            f"Also fetch the full customer history using the customer_id from that transaction. "
            f"Return all data as JSON."
        ),
        expected_output="JSON object with 'transaction' and 'customer_history' keys",
        agent=data_agent,
    )

    task_enrich_ip = Task(
        description=(
            "Using the IP address from the transaction fetched in the previous task:\n"
            "1) Call the enrich_ip_address tool with that IP address to get real geolocation and ISP data.\n"
            "2) Call the fetch_ip_transactions tool with that IP address to get all transactions from that IP.\n"
            "Use the actual tool results — do not fabricate or infer data. Return both results as JSON."
        ),
        expected_output="JSON object with 'ip_enrichment' and 'ip_transactions' keys from real tool results",
        agent=enrichment_agent,
        context=[task_fetch_data],
    )

    task_write_narrative = Task(
        description=(
            f"Chargeback ID: {chargeback_id}\n"
            f"Reason: {chargeback_meta.get('reason_description', 'unauthorized transaction')}\n\n"
            "Using ALL evidence gathered (transaction details, customer history, IP enrichment, "
            "IP transaction history), write a professional chargeback dispute narrative. "
            "The narrative should:\n"
            "- Address the specific reason code / claim\n"
            "- Highlight consistent IP usage across multiple legitimate purchases\n"
            "- Reference matching billing/shipping addresses\n"
            "- Call out the customer's prior purchase history to establish account legitimacy\n"
            "- Be factual, concise, and professional (max 400 words)\n"
            "Return ONLY the narrative text."
        ),
        expected_output="A professional dispute narrative (plain text, max 400 words)",
        agent=analyst_agent,
        context=[task_fetch_data, task_enrich_ip],
    )

    task_compile_package = Task(
        description=(
            "Compile the final evidence package as a JSON object with these exact keys:\n"
            "- transaction: the full transaction dict\n"
            "- customer_history: dict with 'transactions' and 'events' lists\n"
            "- ip_enrichment: dict with geolocation data\n"
            "- ip_transactions: list of transactions from the same IP\n"
            "- narrative: the dispute narrative text\n"
            "Return ONLY the raw JSON object, no markdown fences."
        ),
        expected_output="Raw JSON object with the five keys listed above",
        agent=coordinator_agent,
        context=[task_fetch_data, task_enrich_ip, task_write_narrative],
    )

    # ------------------------------------------------------------------
    # Crew
    # ------------------------------------------------------------------
    crew = Crew(
        agents=[data_agent, enrichment_agent, analyst_agent, coordinator_agent],
        tasks=[task_fetch_data, task_enrich_ip, task_write_narrative, task_compile_package],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()
    raw = result.raw if hasattr(result, "raw") else str(result)

    # Parse the compiled JSON package
    try:
        package = json.loads(raw)
    except json.JSONDecodeError:
        # Crew returned partial data — gracefully degrade
        package = {
            "transaction": {},
            "customer_history": {},
            "ip_enrichment": {},
            "ip_transactions": [],
            "narrative": raw,
        }

    return DisputeEvidence(
        transaction=package.get("transaction", {}),
        chargeback=chargeback_meta,
        customer_history=package.get("customer_history", {}),
        ip_enrichment=package.get("ip_enrichment", {}),
        ip_transactions=package.get("ip_transactions", []),
        narrative=package.get("narrative", ""),
    )
