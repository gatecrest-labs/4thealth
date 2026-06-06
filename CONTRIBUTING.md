Contributing

Thanks for your interest in contributing. Quick checklist:

- Fork the repo and open a branch per feature/fix using kebab-case.
- Follow the repo style: run linters and formatters before committing.

Local development

# Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# Create .env from example
cp .env.example .env
# Generate SECRET_KEY: python manage_users.py secret

# Run dev server
pip install uv
uv sync
uv run python wsgi.py

Testing & CI

- Tests: pytest
- Linting: flake8

Pull request checklist

- [ ] Tests pass (pytest)
- [ ] Linting passes (flake8)
- [ ] Changelog / README updated if needed
- [ ] Security considerations addressed

