# Faultline SDK on PyPI

## For customers

```bash
pip install faultline-sdk
```

```python
import faultline   # not "import faultline_sdk"
```

| What | Name |
|------|------|
| Install (`pip`) | **`faultline-sdk`** |
| Import in Python | **`faultline`** |
| CLI | **`faultline`** (`python -m faultline.cli`) |

The PyPI project name `faultline` belongs to an unrelated package. Ours is **`faultline-sdk`** on [pypi.org/project/faultline-sdk](https://pypi.org/project/faultline-sdk/).

---

## Publishing (maintainers)

The installable package is **`faultline-sdk`** (import name remains `faultline`).

## One-time (you)

- [x] PyPI account + 2FA
- [ ] Create API token on [pypi.org](https://pypi.org/manage/account/token/) (scope: entire account for first upload, or project `faultline-sdk` after first release)
- [ ] Optional: TestPyPI token from [test.pypi.org](https://test.pypi.org/manage/account/token/)

## Build and upload (you run locally)

From repo root:

```powershell
cd sdk
python -m pip install -U build twine
python -m build
```

### TestPyPI (recommended first)

**Use a token from [test.pypi.org](https://test.pypi.org/manage/account/token/)** — not pypi.org. They are separate sites and tokens are not interchangeable.

```powershell
# Avoid Windows keyring serving old/wrong credentials:
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-AgEIcG..."   # paste full TestPyPI token here

python -m twine upload --repository-url https://test.pypi.org/legacy/ dist\*
```

If prompted interactively:

- Username: `__token__` (literally, two underscores each side)
- Password: the **entire** token string including the `pypi-` prefix

#### `403 Forbidden` on upload

| Cause | Fix |
|-------|-----|
| Production token used on TestPyPI | Create a new token at **test.pypi.org** |
| Wrong username | Must be `__token__`, not your email |
| Email not verified | Confirm email on test.pypi.org (check inbox) |
| 2FA not enabled | Enable 2FA on TestPyPI (required for uploads) |
| Stale Windows keyring entry | Set `$env:TWINE_USERNAME` / `$env:TWINE_PASSWORD` as above |
| Token missing upload scope | Create token with scope “Entire account” for first upload |

Verbose errors:

```powershell
python -m twine upload --repository-url https://test.pypi.org/legacy/ dist\* -v
```

Verify install:

```powershell
python -m venv $env:TEMP\fl-pypi-test
& $env:TEMP\fl-pypi-test\Scripts\pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ faultline-sdk==0.24.0
& $env:TEMP\fl-pypi-test\Scripts\python -c "import faultline; print(faultline.start)"
```

### Production PyPI

```powershell
python -m twine upload dist\*
```

Same `__token__` username; use your **production** PyPI token.

After upload:

```bash
pip install faultline-sdk
```

## CI (optional)

Add GitHub secret `PYPI_API_TOKEN` and push a release, or run the **Publish SDK to PyPI** workflow manually from Actions.

## Version bumps

Edit `version` in `sdk/pyproject.toml`, rebuild, upload. Delete `sdk/dist/` before rebuilding.
