"""Dev CLI — exposes pipeline stages without going through HTTP."""
from __future__ import annotations

import json
from pathlib import Path

import click

from src.chunks import Chunk
from src.extract import extract_from_repo


@click.group()
def cli() -> None:
    """Codebase Q&A Agent — dev CLI."""


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--limit", default=50, type=int, show_default=True,
              help="Max chunks to print (counts still report the full total).")
@click.option("--type", "chunk_type", default=None,
              type=click.Choice(["file", "class", "function", "method"]),
              help="Filter output by chunk_type.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON Lines.")
@click.option("--no-tests", is_flag=True, help="Exclude is_test=True chunks.")
def chunk(
    repo_path: Path,
    limit: int,
    chunk_type: str | None,
    as_json: bool,
    no_tests: bool,
) -> None:
    """Extract chunks from a repo and print them.

    Example:
        python -m src.cli chunk /app/repos/flask --limit 50
        python -m src.cli chunk /app/repos/flask --type class --json
    """
    printed = 0
    counts_by_type: dict[str, int] = {}
    test_counts: dict[str, int] = {}

    for c in extract_from_repo(repo_path):
        counts_by_type[c.chunk_type] = counts_by_type.get(c.chunk_type, 0) + 1
        if c.is_test:
            test_counts[c.chunk_type] = test_counts.get(c.chunk_type, 0) + 1
        if no_tests and c.is_test:
            continue
        if chunk_type and c.chunk_type != chunk_type:
            continue
        if printed >= limit:
            continue
        if as_json:
            click.echo(json.dumps(c.to_dict()))
        else:
            _pretty_print(c)
        printed += 1

    click.echo("", err=True)
    click.secho("== Counts ==", err=True, fg="green", bold=True)
    for k in sorted(counts_by_type):
        ts = test_counts.get(k, 0)
        click.echo(f"  {k:<10s}  total={counts_by_type[k]:<6d}  in tests={ts}", err=True)
    click.echo(f"  {'TOTAL':<10s}  total={sum(counts_by_type.values())}", err=True)


def _pretty_print(c: Chunk) -> None:
    header = (
        f"[{c.chunk_type}] {c.symbol_path or '<root>'}  "
        f"({c.file_path}:{c.start_line}-{c.end_line})  loc={c.loc}"
    )
    click.secho(header, fg="cyan", bold=True)
    flags: list[str] = []
    if c.is_test:
        flags.append("test")
    if c.is_async:
        flags.append("async")
    if c.is_private:
        flags.append("private")
    if flags:
        click.echo(f"  flags: {', '.join(flags)}")
    if c.decorators:
        click.echo(f"  decorators: {c.decorators}")
    if c.docstring:
        doc = c.docstring.replace("\n", " ")
        click.echo(f"  doc: {doc[:120]}{'...' if len(doc) > 120 else ''}")
    if c.imports:
        imps = c.imports[:5]
        suffix = f" (+{len(c.imports) - 5} more)" if len(c.imports) > 5 else ""
        click.echo(f"  imports: {imps}{suffix}")
    if c.calls:
        calls = c.calls[:5]
        suffix = f" (+{len(c.calls) - 5} more)" if len(c.calls) > 5 else ""
        click.echo(f"  calls:   {calls}{suffix}")
    # First 3 non-blank lines of code
    code_lines = [ln for ln in c.code.splitlines() if ln.strip()][:3]
    preview = " | ".join(ln.strip() for ln in code_lines)
    if preview:
        click.echo(f"  code:    {preview[:180]}{'...' if len(preview) > 180 else ''}")
    click.echo()


if __name__ == "__main__":
    cli()
