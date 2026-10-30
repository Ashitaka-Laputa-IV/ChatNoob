# Vendor assets

Third-party browser libraries used by `static/app.js`. All pinned to exact
versions and served locally so the UI works offline; there is no build step.

| File | Version | License | Source |
|---|---|---|---|
| `marked.min.js` | 15.0.7 | MIT | https://cdn.jsdelivr.net/npm/marked@15.0.7/marked.min.js |
| `purify.min.js` | 3.2.4 | Apache-2.0 / MPL-2.0 | https://cdn.jsdelivr.net/npm/dompurify@3.2.4/dist/purify.min.js |
| `highlight.min.js` | 11.11.1 | BSD-3-Clause | https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.11.1/highlight.min.js |
| `github-dark.min.css` | 11.11.1 | BSD-3-Clause | https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.11.1/styles/github-dark.min.css |

To upgrade, bump the version in the URL, download again, and update this table.
