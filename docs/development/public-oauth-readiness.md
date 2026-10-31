# Public OAuth readiness

Issue [#46](https://github.com/dm0/gdocs-scope-mcp/issues/46).
Audit date: 2026-10-31. This is preparation material, not evidence of Google
approval, a registered domain or a published website.

## Confirmed project decisions

- Publish the project website through GitHub Pages with a custom domain.
- Investigate `gdocs-scope-mcp.is-a.dev` as the domain candidate.
- Public support and privacy contact: `gdocs-scope-mcp@googlegroups.com`.
- Keep both access modes from #40; `full_drive` remains the compatibility
  default, while `selected_files` requests only `drive.file`.
- Do not purchase domains, submit registration requests, publish pages or
  change Cloud settings as part of this audit.

The bundled client ID starts with project number `988487172113`. This number
comes from the public client configuration; Cloud project ownership, enabled
APIs, client type, branding, test users and verification state have not yet
been inspected successfully in the Cloud Console. Do not infer those settings
from successful development authorization.

## is-a.dev feasibility

**Conclusion: technically suitable for an attempted verification; acceptance
by is-a.dev maintainers and Google remains unverified.**

The [Public Suffix List](https://publicsuffix.org/list/public_suffix_list.dat)
contains the exact rule `is-a.dev` in its private section. Therefore the
candidate's top private domain is `gdocs-scope-mcp.is-a.dev`, rather than
`is-a.dev`. This is an inference from the list and Google's
[authorized-domain rules](https://developers.google.com/identity/verification/authentication-verification),
not a successful OAuth Console validation. Verify that the Console accepts
this exact authorized domain before relying on the candidate.

The registry file `domains/gdocs-scope-mcp.json` returned 404 on inspection,
and an open-PR search for `gdocs-scope-mcp` found no results. This is an
availability observation, not a reservation; recheck before submitting.

is-a.dev supports [GitHub Pages](https://docs.is-a.dev/guides/github-pages/),
[A and TXT records](https://docs.is-a.dev/domain-structure/) and nested
verification records. Its [registration requirements](https://docs.is-a.dev/quickstart/)
require a substantially prepared development-related website. Its
[terms](https://github.com/is-a-dev/register/blob/main/TERMS_OF_SERVICE.md)
permit non-commercial development projects registered through an individual's
GitHub account, prohibit commercial use and leave approval to maintainers.
Registration does not convey ownership of the parent domain or guaranteed
permanent service. Confirm that the intended use meets these conditions.

### DNS and validation proposal

Use the GitHub Pages IPv4 addresses at the candidate name, allowing a Google
Search Console TXT record at that same name. A CNAME cannot coexist with TXT
in one DNS record set. This differs deliberately from is-a.dev's simple
CNAME-only Pages example. Record support is documented by is-a.dev; the
combination still needs registry review and a real DNS/Pages check.

Proposed `domains/gdocs-scope-mcp.json`, **not submitted**:

```json
{
  "owner": {"username": "dm0"},
  "records": {
    "A": [
      "185.199.108.153",
      "185.199.109.153",
      "185.199.110.153",
      "185.199.111.153"
    ]
  }
}
```

The addresses are from GitHub's current
[custom-domain instructions](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site).
Add the exact `google-site-verification=...` value issued to the project
owner's Search Console account as `records.TXT`; never invent a token. Verify
the Domain property `gdocs-scope-mcp.is-a.dev` through
[Search Console](https://support.google.com/webmasters/answer/9008080?hl=en).
Keep the validation record after verification. A URL-prefix HTML verification
is an alternative to investigate, not the basis of this DNS proposal.

GitHub's separate account-level domain verification issues a TXT challenge at
`_github-pages-challenge-dm0.gdocs-scope-mcp.is-a.dev`. Use the precise hostname
and value supplied by GitHub; is-a.dev represents that nested record in its
own JSON file. This verification is distinct from Google's ownership check.
Follow [GitHub's verification procedure](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages).

Prepare and review the complete site first. Protect the domain in the GitHub
account, coordinate the Pages custom-domain setting with the registry change,
enable HTTPS, and check all public URLs. GitHub recommends configuring the
site before pointing DNS at it, while the is-a.dev example configures it after
merge; avoid an unclaimed DNS interval by completing account verification
first. Do not activate either side without an approved deployment sequence.

Proposed public URLs, not live:

- Homepage: `https://gdocs-scope-mcp.is-a.dev/`
- Privacy: `https://gdocs-scope-mcp.is-a.dev/privacy.html`
- Terms: `https://gdocs-scope-mcp.is-a.dev/terms.html`

## Scope audit

Current source: `src/gdocs_scope_mcp/google_api/access.py`.
Scope suffixes below are relative to `https://www.googleapis.com/auth/`.

| Mode | Requested scope | Classification | Reason / submission decision |
| --- | --- | --- | --- |
| selected | `drive.file` | Non-sensitive | Read and edit selected/app-created Docs; temporary image creation and cleanup. Retain. |
| full | `drive` | Restricted | Account-wide document discovery and operations on existing accessible files. Requires a specific justification for broad discovery. |
| full | `drive.readonly` | Restricted | Current compatibility request; overlaps `drive`. No independent necessity established. |
| full | `documents` | Sensitive | Current compatibility request; Docs methods also accept `drive`. No independent necessity established. |
| full | `drive.file` | Non-sensitive | Current compatibility request; overlaps `drive`. No independent necessity established. |

Classifications: [Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
and [Docs scopes](https://developers.google.com/workspace/docs/api/auth).
Do not submit redundant scopes with invented justifications. A proposed
minimal full-mode request is `drive` alone, subject to a separately tested
authorization/refresh transition and live feature regression. This audit does
not change the request or revoke existing grants.

## Google review requirements to resolve

- [Brand verification](https://developers.google.com/identity/verification/authentication-verification):
  same-domain homepage/privacy, domain ownership associated with a project
  Owner/Editor, accurate branding and reachable contacts. A free subdomain
  does not waive review.
- [Support address](https://support.google.com/cloud/answer/15549049?hl=en):
  a Google Group managed by the logged-in administrator is eligible. Confirm
  the supplied group is selectable and accepts support mail; do not send a
  test message without authorization. Review archive visibility before
  inviting users to send information there.
- [AI client designation](https://support.google.com/cloud/answer/15549257?hl=en):
  inspect the AI-powered-agent checkbox for the Desktop client. Both MCP
  access modes are agent workflows; human consent alone does not create a
  separate non-agent product. If a standard interactive API product is later
  added, Google requires a separate client for that workflow.
- [Restricted-scope review](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification):
  assess the actual MCP-host/AI-provider data path. Do not assume a security
  assessment exemption because the MCP process uses STDIO or runs locally.
  Server storage/transmission can make an annual assessment applicable.
- [OAuth policy](https://developers.google.com/identity/protocols/oauth2/policies):
  review minimum scopes, production/development project separation and token
  protection. Owner-only JSON permissions do not provide encryption at rest.
  The package currently stores refresh credentials without application-level
  encryption; document host protections and resolve the production requirement
  before claiming compliance. Verify the registered Desktop client type;
  public native-client configuration must not be confused with confidential
  Web client credentials.
- [Workspace data policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy):
  review permitted use, transfers to AI providers and model-training terms
  against the actual deployment. The package cannot promise another host's
  data retention or training practices.

## Remaining execution and evidence

1. Review the local [homepage](../../website/index.html),
   [privacy policy](../../website/privacy.html)
   and [terms](../../website/terms.html). The static site needs no JavaScript,
   build step, external fonts or analytics. Relative links work under a Pages
   project path and a custom domain. No deployment workflow is enabled yet.
2. Confirm non-commercial eligibility, chosen name and ownership of `dm0`;
   obtain real Google/GitHub verification challenges through the owner account.
3. Inspect the target Cloud project: owners, enabled Docs/Drive/Picker APIs,
   Desktop client, AI designation, branding, audience and Verification Center.
4. Resolve the minimum scope set and data-policy/protection requirements;
   prepare the corresponding demo and scope justification.
5. Present concrete site, DNS and Cloud changes for approval. Then publish,
   register/verify the domain and complete branding/data-access submissions.
6. Obtain Google's required approvals and verify consent from a user outside
   the test-user list, a bounded authorized document operation, refresh after
   restart and a clean installation from the intended public Git revision.

#46 remains open throughout preparation. Prior test-user checks in #39/#40 do
not prove public availability. No domain registration, external PR, email,
Cloud update, verification submission or Git push was performed for this audit.

## Local site checks

The `website/` directory is the static publication artifact. Configure a future
GitHub Pages Actions workflow to upload this directory;
[branch-source Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
publishing supports only the root or `/docs`, not an arbitrary `/website`
folder. Do not publish the repository root with credentials or research files.
Deployment workflow creation and execution remain separate from this preview.

All three HTML pages were opened in the browser. The homepage and terms were
also inspected at a 390-pixel viewport; navigation wraps and body text remains
readable. Desktop rendering was inspected for the homepage and privacy policy.
The preview uses only local static assets. The draft banners must remain until
owner review is complete. Final publication also needs an effective date,
operator identity and the reviewed Google data-use disclosure.

Package metadata declares MIT, but no standalone `LICENSE` file was found in
the working tree. Confirm the intended license text and attribution before
publishing final terms; the draft does not invent a copyright holder.
