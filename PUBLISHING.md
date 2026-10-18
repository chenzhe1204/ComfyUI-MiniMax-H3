# Publishing checklist

The repository metadata is already configured for:

- GitHub: `chenzhe1204/ComfyUI-MiniMax-H3`
- ComfyUI Registry PublisherId: `chenzhe1204`
  (<https://registry.comfy.org/publishers/chenzhe1204>)

## 1. Push the Git repository

Create the public GitHub repository `ComfyUI-MiniMax-H3` under `chenzhe1204`,
then push:

```sh
git remote -v
git push -u origin main
```

This project was initialized and committed locally. Pushing requires your
GitHub credentials; no credentials are stored in the repository.

## 2. Publish to the ComfyUI Registry

Follow the official instructions at
<https://docs.comfy.org/registry/publishing>. The short version is:

1. Create/sign in to the publisher account at <https://registry.comfy.org>.
2. Generate a Registry publishing API key.
3. Install the Comfy CLI (for example `pip install comfy-cli`).
4. From this directory, run the publish command (for example
   `comfy node publish`) and provide the API key when prompted.

The `pyproject.toml` already contains `[tool.comfy]` with the PublisherId and
DisplayName. `.comfyignore` excludes tests and GitHub metadata from the package.

## 3. Post-publish checks

- Confirm the Registry listing shows the model-license and territory warning.
- Do not upload model weights or the h3.c binary.
- Run `python scripts/doctor.py --mode ref2va` on a clean machine.
- Tag the release (`v0.1.0`) and attach release notes, not weights.
