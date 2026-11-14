"""No text the website shows has a parenthesis in it."""
import ast
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
# The application files whose strings reach a page, a notification or an email
SOURCES = ["views.py", "forms.py", "scheduling.py", "notifications.py", "timeline.py", "models.py",
           "context_processors.py", "templatetags/status.py"]


class NoParenthesesTests(SimpleTestCase):
    def test_no_template_text_has_a_parenthesis(self):
        found = []
        for path in sorted((ROOT / "templates").rglob("*.html")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                shown = " ".join(re.findall(r'(?:title|aria-label|placeholder|alt|value)="([^"]*)"', line))
                # What is left of the line once template tags, variables and HTML tags are taken out
                text = re.sub(r"\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}", " ", line)
                text = re.sub(r"<[^>]*>", " ", text)
                if "(" in text + shown or ")" in text + shown:
                    found.append(f"{path.relative_to(ROOT)}:{number}: {(text + shown).strip()}")
        self.assertEqual(found, [])

    def test_no_message_label_or_error_has_a_parenthesis(self):
        found = []
        for name in SOURCES:
            tree = ast.parse((ROOT / "ops" / name).read_text(encoding="utf-8"))
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body:
                    first = node.body[0]
                    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                        docstrings.add(id(first.value))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
                        and ("(" in node.value or ")" in node.value)):
                    found.append(f"ops/{name}:{node.lineno}: {node.value.strip()}")
        self.assertEqual(found, [])
