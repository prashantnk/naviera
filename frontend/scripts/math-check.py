"""Zero Frontend Math audit (AGENTS.md section 1, plan item B14).

Fails (exit code 1) when frontend source does arithmetic on a money field, for
example ``payment_details.shipment_total_value + freight`` or
``rows.reduce((sum, r) => sum + r.amount, 0)``. Every rupee shown on screen must
come from a backend payload; the frontend only formats it.

How it works:
  * The TypeScript compiler (``frontend/node_modules/typescript``) parses each
    product ``.ts`` / ``.tsx`` file into an AST, so comments, strings and JSX
    text such as ``GST / Indirect Taxes`` can never cause a false positive.
  * Every binary ``+ - * / %`` and compound ``+= -= *= /=`` is inspected. It is a
    violation when either operand is a money identifier: an identifier, member
    access or string-keyed element access whose name contains amount, price,
    cost, freight, fee, tax, gst, charge, collectible, balance, refund, delta,
    COD or a shipment / invoice / declared / total value. Wrappers that do not
    change the number (parentheses, ``Number()``, ``parseFloat()``, ``x!``,
    ``x as T``, ``x ?? 0``, ``x || 0``) are looked through.
  * ``+`` with a string or template operand is concatenation (formatting), not
    math, and is allowed.
  * A line can be exempted only with an inline ``math-check: ignore <reason>``
    comment, so each exemption is visible in review.

Spring analogy: an ArchUnit rule that fails the build when a controller layer
class calls a pricing method, except here the "layer" is the whole frontend.

Run: ``python3 scripts/math-check.py`` (wired into ``npm run test:audit``).
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from typing import List, Optional

FRONTEND_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC_DIR = os.path.join(FRONTEND_DIR, "src")
NVM_NODE_GLOB = os.path.expanduser("~/.nvm/versions/node/*/bin/node")
NODE_TIMEOUT_SECONDS = 300

EXIT_CLEAN = 0
EXIT_VIOLATIONS = 1
EXIT_TOOLING_ERROR = 2

# The AST walker runs in Node with the project's own TypeScript compiler. It is
# embedded (piped on stdin) so the audit stays a single file.
AST_WALKER_JS = r"""
const fs = require("fs");
const path = require("path");
const ts = require(path.join(process.argv[2], "node_modules", "typescript"));

const SRC_DIR = path.join(process.argv[2], "src");
const EXCLUDED_DIRS = new Set(["api_client", "node_modules", "__tests__"]);
const EXCLUDED_SUFFIXES = [".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".d.ts"];
const IGNORE_MARKER = "math-check: ignore";
const MONEY_NAME = new RegExp(
  "amount|price|cost|freight|fee|tax|gst|charge|collectible|balance|refund|delta" +
    "|shipment_?value|total_?value|invoice_?value|declared_?value",
  "i",
);
const COD_NAME = /(^|_)cod($|_)|^cod[A-Z]|Cod($|[A-Z_])|COD/;
const ARITHMETIC = new Set([
  ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.AsteriskToken,
  ts.SyntaxKind.SlashToken, ts.SyntaxKind.PercentToken,
  ts.SyntaxKind.PlusEqualsToken, ts.SyntaxKind.MinusEqualsToken,
  ts.SyntaxKind.AsteriskEqualsToken, ts.SyntaxKind.SlashEqualsToken,
]);
const PLUS = new Set([ts.SyntaxKind.PlusToken, ts.SyntaxKind.PlusEqualsToken]);
const PASS_THROUGH_CALLS = new Set(["Number", "parseFloat", "parseInt"]);
const FALLBACK_OPS = new Set([
  ts.SyntaxKind.QuestionQuestionToken, ts.SyntaxKind.BarBarToken,
]);

function listFiles(dir, out) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!EXCLUDED_DIRS.has(entry.name)) listFiles(full, out);
    } else if (/\.tsx?$/.test(entry.name) && !EXCLUDED_SUFFIXES.some((s) => entry.name.endsWith(s))) {
      out.push(full);
    }
  }
  return out;
}

function unwrap(node) {
  for (;;) {
    if (ts.isParenthesizedExpression(node) || ts.isNonNullExpression(node) ||
        ts.isAsExpression(node) || ts.isTypeAssertionExpression(node)) {
      node = node.expression;
    } else if (ts.isBinaryExpression(node) && FALLBACK_OPS.has(node.operatorToken.kind)) {
      node = node.left;
    } else if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) &&
               PASS_THROUGH_CALLS.has(node.expression.text) && node.arguments.length > 0) {
      node = node.arguments[0];
    } else {
      return node;
    }
  }
}

function moneyName(node) {
  node = unwrap(node);
  let name = null;
  if (ts.isIdentifier(node)) name = node.text;
  else if (ts.isPropertyAccessExpression(node)) name = node.name.text;
  else if (ts.isElementAccessExpression(node) && ts.isStringLiteralLike(node.argumentExpression)) {
    name = node.argumentExpression.text;
  }
  return name !== null && (MONEY_NAME.test(name) || COD_NAME.test(name)) ? name : null;
}

function isStringy(node) {
  node = unwrap(node);
  return ts.isStringLiteralLike(node) || ts.isTemplateExpression(node);
}

const violations = [];
let scanned = 0;
for (const file of listFiles(SRC_DIR, [])) {
  scanned += 1;
  const text = fs.readFileSync(file, "utf8");
  const lines = text.split("\n");
  const kind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const seenLines = new Set();
  const visit = (node) => {
    if (ts.isBinaryExpression(node) && ARITHMETIC.has(node.operatorToken.kind)) {
      const concatenation = PLUS.has(node.operatorToken.kind) &&
        (isStringy(node.left) || isStringy(node.right));
      const name = concatenation ? null : (moneyName(node.left) || moneyName(node.right));
      if (name) {
        const line = source.getLineAndCharacterOfPosition(node.operatorToken.getStart(source)).line;
        if (!seenLines.has(line) && !lines[line].includes(IGNORE_MARKER)) {
          seenLines.add(line);
          violations.push({
            path: path.relative(SRC_DIR, file),
            line: line + 1,
            field: name,
            source: lines[line].trim(),
          });
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
}
process.stdout.write(JSON.stringify({ scanned, violations }));
"""


def _find_node() -> Optional[str]:
    """Locates a Node.js binary (PATH first, then the NVM install from AGENTS §9.C).

    Returns:
        Absolute path to ``node``, or None when Node is not installed.
    """
    on_path = shutil.which("node")
    if on_path:
        return on_path
    candidates = sorted(glob.glob(NVM_NODE_GLOB))
    return candidates[-1] if candidates else None


def _run_ast_walker(node_binary: str) -> dict:
    """Runs the embedded TypeScript AST walker over ``frontend/src``.

    Args:
        node_binary: Path to the Node.js executable.

    Returns:
        Parsed walker output: ``{"scanned": int, "violations": [...]}``.

    Raises:
        RuntimeError: If the walker fails (for example TypeScript is not installed).
    """
    completed = subprocess.run(
        [node_binary, "-", FRONTEND_DIR],
        input=AST_WALKER_JS,
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "AST walker failed")
    return json.loads(completed.stdout)


def _format_violations(violations: List[dict]) -> List[str]:
    """Renders one ``file:line [field] : source`` line per violation.

    Args:
        violations: Walker violation records.

    Returns:
        Printable report lines.
    """
    return [
        f"{item['path']}:{item['line']} [{item['field']}] : {item['source']}" for item in violations
    ]


def main() -> int:
    """Scans the frontend and prints every money-arithmetic violation.

    Returns:
        0 when clean, 1 when violations were found, 2 when the tooling is missing.
    """
    node_binary = _find_node()
    if node_binary is None:
        print("math-check: Node.js not found (load NVM, see AGENTS.md §9.C).")
        return EXIT_TOOLING_ERROR
    try:
        result = _run_ast_walker(node_binary)
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        print(f"math-check: could not run the TypeScript AST walker: {error}")
        return EXIT_TOOLING_ERROR
    violations = result["violations"]
    for line in _format_violations(violations):
        print(line)
    print(
        f"math-check: scanned {result['scanned']} files, "
        f"{len(violations)} money-arithmetic line(s)."
    )
    return EXIT_VIOLATIONS if violations else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
