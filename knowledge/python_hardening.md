# Python Security Hardening Checklist

## 1. Dependency Management
- [ ] **Use Virtual Environments:** Always isolate project dependencies using `venv` or `conda`.
- [ ] **Pin Dependencies:** Use exact versions in `requirements.txt` or `poetry.lock` to prevent "dependency confusion" or breaking changes.
- [ ] **Audit Dependencies:** Regularly run `pip-audit` or `safety check` to find known vulnerabilities (CVEs) in your packages.
- [ ] **Verify Hashes:** Use `--generate-hashes` with `pip-compile` (pip-tools) to ensure package integrity.
- [ ] **Minimize Dependencies:** Only install what is strictly necessary to reduce the attack surface.

## 2. Code Quality & Static Analysis
- [ ] **Static Analysis (SAST):** Use `bandit` to find common security issues (e.g., hardcoded passwords, insecure imports).
- [ ] **Linting:** Use `ruff` or `flake8` with security plugins to maintain code quality.
- [ ] **Type Checking:** Use `mypy` to prevent type-related bugs that could lead to logic vulnerabilities.
- [ ] **Secret Scanning:** Use `gitleaks` or `trufflehog` to ensure no secrets are committed to version control.

## 3. Input Validation & Sanitization
- [ ] **Never Trust User Input:** Validate all input against a strict schema (use `pydantic` or `marshmallow`).
- [ ] **Prevent SQL Injection:** Always use parameterized queries (ORMs like SQLAlchemy or Django ORM do this by default). Never use f-strings for SQL.
- [ ] **Prevent Command Injection:** Avoid `os.system()` or `subprocess.run(shell=True)`. Use `subprocess.run()` with a list of arguments.
- [ ] **Sanitize HTML/XML:** Use `bleach` for HTML sanitization and `defusedxml` to prevent XML External Entity (XXE) attacks.
- [ ] **Path Validation:** Use `pathlib` and ensure paths stay within intended directories (prevent Directory Traversal).

## 4. Authentication & Authorization
- [ ] **Secure Password Hashing:** Use `argon2-cffi` or `bcrypt`. Never use MD5 or SHA1 for passwords.
- [ ] **Use Established Libraries:** Don't "roll your own" auth. Use `Flask-Login`, `Django Auth`, or `FastAPI Users`.
- [ ] **Implement RBAC/ABAC:** Ensure strict Role-Based Access Control for all sensitive endpoints.
- [ ] **Session Security:** Set `HttpOnly`, `Secure`, and `SameSite=Lax/Strict` flags on cookies.

## 5. Data Protection & Encryption
- [ ] **Environment Variables:** Store secrets in `.env` files (loaded via `python-dotenv`) or a Secret Manager (AWS Secrets Manager, HashiCorp Vault).
- [ ] **TLS/SSL:** Ensure all network communication is encrypted. Use `certifi` for up-to-date CA bundles.
- [ ] **Strong Cryptography:** Use the `cryptography` library for encryption. Avoid `pycrypto` (unmaintained).
- [ ] **Sensitive Data Masking:** Ensure PII (Personally Identifiable Information) is masked in logs and UI.

## 6. Error Handling & Logging
- [ ] **Generic Error Messages:** Don't leak stack traces or system info to the end-user.
- [ ] **Secure Logging:** Ensure secrets, tokens, and PII are never written to logs.
- [ ] **Centralized Logging:** Use a secure, append-only logging system for audit trails.

## 7. Environment & Deployment
- [ ] **Run as Non-Root:** Ensure the Python process runs as a low-privileged user in production/Docker.
- [ ] **Disable Debug Mode:** Ensure `DEBUG = False` in production (Django/Flask/FastAPI).
- [ ] **Update Python:** Regularly update the Python interpreter to the latest patched version.
- [ ] **Resource Limits:** Use `ulimit` or Docker resource limits to prevent Denial of Service (DoS) via resource exhaustion.

## 8. Web Specific (OWASP Top 10)
- [ ] **CSRF Protection:** Enable Cross-Site Request Forgery protection (standard in Django, use `Flask-WTF` for Flask).
- [ ] **XSS Prevention:** Use templating engines like Jinja2 that auto-escape HTML by default.
- [ ] **CORS Policy:** Implement a strict Content Security Policy (CSP) and Cross-Origin Resource Sharing (CORS) settings.
