"""Renderer deterministici e scrittura sicura degli artefatti Preflight."""
from __future__ import annotations

from html import escape
import json
import os
from pathlib import Path
import tempfile
from typing import Literal

import yaml

from starkeno.preflight_lint import Finding, finding_sort_key
from starkeno.preflight_patch import Comparison
from starkeno.preflight_schema import Blueprint, FrozenModel
from starkeno.preflight_simulate import ScenarioTotals, SimulationReport


ReportFormat = Literal["json", "yaml", "markdown", "html"]
_FORMATS = frozenset(("json", "yaml", "markdown", "html"))
_SCENARIOS = ("optimistic", "typical", "prudent", "maximum")


class PreflightAnalysis(FrozenModel):
    """Analisi immutabile, con il percorso sorgente confinato alla scrittura locale."""

    blueprint: Blueprint
    findings: tuple[Finding, ...]
    simulation: SimulationReport
    comparison: Comparison | None = None
    source_path: Path | None = None


def render_analysis(analysis: PreflightAnalysis, *, format: ReportFormat) -> str:
    """Renderizza l'analisi senza accedere a filesystem, rete o orologio."""
    _validate_format(format)
    payload = analysis.model_dump(mode="json", exclude={"source_path"})
    if format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if format == "yaml":
        return yaml.safe_dump(payload, allow_unicode=True, sort_keys=True)
    if format == "markdown":
        return _render_markdown(analysis)
    return _render_html(analysis)


def write_analysis(analysis: PreflightAnalysis, destination: Path, *, format: str) -> Path:
    """Scrive UTF-8 solo dopo un render valido e non sovrascrive l'input locale."""
    content = render_analysis(analysis, format=format)  # type: ignore[arg-type]
    resolved_destination = Path(destination).resolve()
    if analysis.source_path is not None and resolved_destination == analysis.source_path.resolve():
        raise ValueError("La destinazione del report non puo coincidere con l'input.")
    resolved_destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{resolved_destination.name}.", suffix=".tmp", dir=resolved_destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            fsync = getattr(os, "fsync", None)
            if callable(fsync):
                fsync(handle.fileno())
        os.replace(temporary, resolved_destination)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return resolved_destination


def _validate_format(format: str) -> None:
    if format not in _FORMATS:
        raise ValueError(f"Formato report non supportato: {format}")


def _render_markdown(analysis: PreflightAnalysis) -> str:
    lines = [
        "# Report Preflight",
        "",
        "## Goal",
        "",
        _markdown_inline(analysis.blueprint.goal.description),
        "",
        f"Deliverable: {_markdown_inline(analysis.blueprint.goal.deliverable)}",
        "",
        "## Findings principali",
        "",
    ]
    findings = tuple(sorted(analysis.findings, key=finding_sort_key))[:5]
    if findings:
        for index, finding in enumerate(findings, start=1):
            lines.extend(
                (
                    f"{index}. [{_markdown_inline(finding.severity)}] "
                    f"{_markdown_inline(finding.rule_id)}",
                    f"   - Category: {_markdown_inline(finding.category)}",
                    f"   - Message: {_markdown_inline(finding.message)}",
                    "   - Evidence:",
                    _markdown_block(_json_text(finding.model_dump(mode="json")["evidence"])),
                    f"   - Locations: {_markdown_inline(', '.join(finding.locations))}",
                    f"   - Suggestion: {_markdown_inline(finding.suggestion)}",
                    f"   - Source: {_markdown_inline(finding.source)}",
                )
            )
    else:
        lines.append("- Nessun rilievo deterministico.")
    lines.extend(("", "## Scenari", "", "| Scenario | Presenza | Token | Chiamate LLM | Tool | Latenza ms | Costo |"))
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | --- |")
    for name in _SCENARIOS:
        scenario = getattr(analysis.simulation, name)
        lines.append(_markdown_scenario(name, scenario))
    lines.extend(
        (
            "",
            "## Assunzioni e confidenza",
            "",
            f"Confidence complessiva: {_markdown_inline(analysis.simulation.confidence)}",
            "",
            "Provenance delle stime:",
        )
    )
    for provenance in _provenances(analysis.blueprint):
        lines.append(f"- {_markdown_inline(provenance)}")
    if analysis.simulation.assumptions:
        lines.append("")
        lines.append("Assunzioni:")
        for assumption in analysis.simulation.assumptions:
            lines.append(f"- {_markdown_inline(assumption)}")
    lines.extend(("", "## Audit delle stime nodo", ""))
    lines.extend(_markdown_estimate_audit(analysis.blueprint))
    lines.extend(("", "## Prezzi e limiti", ""))
    lines.append(
        "Prezzi sconosciuti (caso peggiore): "
        + (
            _markdown_inline(", ".join(analysis.simulation.unknown_prices))
            if analysis.simulation.unknown_prices
            else "nessuno"
        )
    )
    lines.append(f"Limite massimo: {_markdown_inline(analysis.simulation.maximum_status)}")
    lines.extend(("", "## Confronto", ""))
    lines.append(_markdown_block(_comparison_text(analysis.comparison)))
    return "\n".join(lines) + "\n"


def _markdown_scenario(name: str, scenario: ScenarioTotals | None) -> str:
    if scenario is None:
        return f"| {_markdown_inline(name)} | assente | — | — | — | — | unknown |"
    tokens = scenario.input_tokens + scenario.output_tokens + scenario.cache_read_tokens + scenario.cache_write_tokens
    cost = "unknown" if scenario.cost is None else f"{scenario.cost} {scenario.currency or ''}".strip()
    return (
        f"| {_markdown_inline(name)} | presente | {_markdown_inline(tokens)} | "
        f"{_markdown_inline(scenario.llm_calls)} | {_markdown_inline(scenario.tool_calls)} | "
        f"{_markdown_inline(scenario.latency_ms)} | {_markdown_inline(cost)} |"
    )


def _render_html(analysis: PreflightAnalysis) -> str:
    findings = tuple(sorted(analysis.findings, key=finding_sort_key))[:5]
    finding_items = "".join(
        "<li><strong>"
        f"{_dynamic(finding.severity)} {_dynamic(finding.rule_id)}"
        "</strong><dl>"
        f"<dt>Category</dt><dd>{_dynamic(finding.category)}</dd>"
        f"<dt>Message</dt><dd>{_dynamic(finding.message)}</dd>"
        f"<dt>Evidence</dt><dd><pre>{_dynamic(_json_text(finding.model_dump(mode='json')['evidence']))}</pre></dd>"
        f"<dt>Locations</dt><dd>{_dynamic(', '.join(finding.locations))}</dd>"
        f"<dt>Suggestion</dt><dd>{_dynamic(finding.suggestion)}</dd>"
        f"<dt>Source</dt><dd>{_dynamic(finding.source)}</dd>"
        "</dl></li>"
        for finding in findings
    ) or "<li>Nessun rilievo deterministico.</li>"
    scenario_rows = "".join(_html_scenario(name, getattr(analysis.simulation, name)) for name in _SCENARIOS)
    provenance_items = "".join(f"<li>{_dynamic(item)}</li>" for item in _provenances(analysis.blueprint))
    assumption_items = "".join(
        f"<li>{_dynamic(assumption)}</li>" for assumption in analysis.simulation.assumptions
    ) or "<li>Nessuna assunzione aggiuntiva.</li>"
    unknown_prices = ", ".join(analysis.simulation.unknown_prices) or "nessuno"
    return """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'">
<title>Report Preflight</title>
<style>
body { background: #fff; color: #17212b; font-family: system-ui, sans-serif; line-height: 1.45; margin: 2rem auto; max-width: 72rem; padding: 0 1rem; }
table { border-collapse: collapse; width: 100%; } th, td { border: 1px solid #cbd5e1; padding: .45rem; text-align: left; } th { background: #f1f5f9; } code, pre { overflow-wrap: anywhere; white-space: pre-wrap; } dt { font-weight: 700; } dd { margin: 0 0 .5rem; }
</style>
</head>
<body>
<main>
<h1>Report Preflight</h1>
<section><h2>Goal</h2><p>""" + _dynamic(analysis.blueprint.goal.description) + """</p><p>Deliverable: """ + _dynamic(analysis.blueprint.goal.deliverable) + """</p></section>
<section><h2>Findings principali</h2><ol>""" + finding_items + """</ol></section>
<section><h2>Scenari</h2><table><thead><tr><th>Scenario</th><th>Presenza</th><th>Token</th><th>LLM</th><th>Tool</th><th>Latenza ms</th><th>Costo</th></tr></thead><tbody>""" + scenario_rows + """</tbody></table></section>
<section><h2>Assunzioni e confidenza</h2><p>Confidence complessiva: """ + _dynamic(analysis.simulation.confidence) + """</p><h3>Provenance delle stime</h3><ul>""" + provenance_items + """</ul><h3>Assunzioni</h3><ul>""" + assumption_items + """</ul></section>
<section><h2>Audit delle stime nodo</h2>""" + _html_estimate_audit(analysis.blueprint) + """</section>
<section><h2>Prezzi e limiti</h2><p>Prezzi sconosciuti (caso peggiore): """ + _dynamic(unknown_prices) + """</p><p>Limite massimo: """ + _dynamic(analysis.simulation.maximum_status) + """</p></section>
<section><h2>Confronto</h2><pre>""" + _dynamic(_comparison_text(analysis.comparison)) + """</pre></section>
</main>
</body>
</html>
"""


def _html_scenario(name: str, scenario: ScenarioTotals | None) -> str:
    if scenario is None:
        return f"<tr><td>{_dynamic(name)}</td><td>assente</td><td colspan=\"5\">unknown</td></tr>"
    tokens = scenario.input_tokens + scenario.output_tokens + scenario.cache_read_tokens + scenario.cache_write_tokens
    cost = "unknown" if scenario.cost is None else f"{scenario.cost} {scenario.currency or ''}".strip()
    return (
        f"<tr><td>{_dynamic(name)}</td><td>presente</td><td>{_dynamic(tokens)}</td>"
        f"<td>{_dynamic(scenario.llm_calls)}</td><td>{_dynamic(scenario.tool_calls)}</td>"
        f"<td>{_dynamic(scenario.latency_ms)}</td><td>{_dynamic(cost)}</td></tr>"
    )


def _provenances(blueprint: Blueprint) -> tuple[str, ...]:
    values = {
        estimate.provenance
        for node in blueprint.nodes
        for estimate in (
            node.budget.instructions,
            node.budget.dynamic_context,
            node.budget.output,
            node.budget.cacheable_fraction,
            node.budget.latency_ms,
            node.budget.retry_probability,
        )
    }
    values.update(
        transition.probability.provenance
        for transition in blueprint.transitions
        if transition.probability is not None
    )
    values.update(
        node.budget.fixed_tool_cost.provenance
        for node in blueprint.nodes
        if node.budget.fixed_tool_cost is not None
    )
    return tuple(sorted(values)) or ("unknown",)


def _comparison_text(comparison: Comparison | None) -> str:
    if comparison is None:
        return "assente"
    return _json_text(comparison.model_dump(mode="json"))


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _markdown_inline(value: object) -> str:
    """Rende un valore sicuro in una singola cella/riga Markdown."""
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ↵ ")
    escaped = escape(normalized, quote=True)
    for character in ("\\", "`", "*", "_", "[", "]", "(", ")", "!", "|", "#", "+", "-", "~"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _markdown_block(value: str) -> str:
    """Rende dati strutturati in un code block indentato, senza fence controllabili dall'input."""
    return "\n".join(f"    {_markdown_inline(line)}" for line in value.splitlines())


def _estimate_rows(blueprint: Blueprint) -> tuple[tuple[str, str, object], ...]:
    dimensions = (
        "instructions",
        "dynamic_context",
        "output",
        "cacheable_fraction",
        "latency_ms",
        "retry_probability",
    )
    rows = tuple(
        (node.id, dimension, getattr(node.budget, dimension))
        for node in sorted(blueprint.nodes, key=lambda item: item.id)
        for dimension in dimensions
    )
    tool_cost_rows = tuple(
        (node.id, "fixed_tool_cost", node.budget.fixed_tool_cost)
        for node in sorted(blueprint.nodes, key=lambda item: item.id)
        if node.budget.fixed_tool_cost is not None
    )
    return rows + tool_cost_rows


def _markdown_estimate_audit(blueprint: Blueprint) -> tuple[str, ...]:
    rows = (
        "| Nodo | Dimensione | min | typical | max | valuta | provenance | confidence | reason |",
        "| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |",
    )
    return rows + tuple(
        "| "
        f"{_markdown_inline(node_id)} | {_markdown_inline(dimension)} | "
        f"{_markdown_inline(estimate.min)} | {_markdown_inline(estimate.typical)} | "
        f"{_markdown_inline(estimate.max)} | {_markdown_inline(getattr(estimate, 'currency', '—'))} | "
        f"{_markdown_inline(estimate.provenance)} | "
        f"{_markdown_inline(estimate.confidence)} | {_markdown_inline(estimate.reason)} |"
        for node_id, dimension, estimate in _estimate_rows(blueprint)
    )


def _html_estimate_audit(blueprint: Blueprint) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_dynamic(node_id)}</td><td>{_dynamic(dimension)}</td>"
        f"<td>{_dynamic(estimate.min)}</td><td>{_dynamic(estimate.typical)}</td>"
        f"<td>{_dynamic(estimate.max)}</td><td>{_dynamic(getattr(estimate, 'currency', '—'))}</td>"
        f"<td>{_dynamic(estimate.provenance)}</td>"
        f"<td>{_dynamic(estimate.confidence)}</td><td>{_dynamic(estimate.reason)}</td>"
        "</tr>"
        for node_id, dimension, estimate in _estimate_rows(blueprint)
    )
    return (
        "<table><thead><tr><th>Nodo</th><th>Dimensione</th><th>min</th><th>typical</th>"
        "<th>max</th><th>valuta</th><th>provenance</th><th>confidence</th><th>reason</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _dynamic(value: object) -> str:
    return escape(str(value), quote=True)
