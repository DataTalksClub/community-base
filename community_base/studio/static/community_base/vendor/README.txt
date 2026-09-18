Vendored third-party browser assets for the Studio shell.

Everything in this directory is copied verbatim from an upstream release and is not
edited here. The Studio shell serves these from the site's own origin so a site with a
`script-src 'self'` Content-Security-Policy can run the shell unchanged, and so no
third-party host decides what executes on a staff surface.

lucide.min.js
  Package:  lucide (npm), https://lucide.dev
  Version:  1.47.0
  License:  ISC, see lucide-LICENSE.txt
  Source:   https://registry.npmjs.org/lucide/-/lucide-1.47.0.tgz, dist/umd/lucide.min.js
  Replaces:
            the unversioned CDN tag the shell loaded before this file existed, described in
            CHANGELOG.md. The literal URL is deliberately not repeated here: the repository
            greps for it to stop it coming back.
  sha256:   c3291ea757ff3da0fc45a41d3ff60d61da9b257314962c5cdded94ca0df05d7a

  Re-derive and verify:

    npm pack lucide@1.47.0
    tar xzf lucide-1.47.0.tgz
    sha256sum package/dist/umd/lucide.min.js

  This is the UMD build: it defines `window.lucide` with `createIcons()`, which
  `community_base/studio.js` calls with no arguments, and which by default replaces every
  element carrying `data-lucide` with the named icon. Any replacement must keep that API.

To upgrade, replace the file, update the version, URL and hash above, update the
`Vendored icon library` section in `community_base/studio/README.md`, and re-run
`uv run pytest tests/studio/test_shell_icon_script.py`.
