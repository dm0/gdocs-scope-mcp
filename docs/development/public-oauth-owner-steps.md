# Owner-run publication and verification

For [#46](https://github.com/dm0/gdocs-scope-mcp/issues/46).
Prepared on 2026-11-02 from the [readiness audit](public-oauth-readiness.md).
The owner performs all external submissions. No step below has been submitted
or completed by the assistant. Replace every placeholder before using a file.

## 1. Prepare the public website

Review `website/index.html`, `privacy.html` and `terms.html`. Before publishing:

- Confirm the operator identity and effective date, finalize license text and
  attribution, and review the data-use policy against the intended MCP hosts.
- Remove the unpublished-draft banners after review. Retain the explanation
  that unrestricted public OAuth approval is still pending.
- Keep the support address `gdocs-scope-mcp@googlegroups.com`. In Google Groups,
  check that external senders can post, messages reach you and conversations
  are visible only to the intended members. Receiving support mail does not
  require opening group membership or archives to everyone. You can test from
  an account outside the group yourself. See [Groups permissions](https://support.google.com/groups/answer/2464975?hl=en).

Use the inactive [Pages workflow template](../../research/publication/github-pages.yml).
After reviewing it, copy it to `.github/workflows/pages.yml` and publish the
approved source to `main`. In repository Settings > Pages, select GitHub Actions
as the source. Run the workflow manually on `main`, checking its `publish`
input only when you intend to publish. It uploads only `website/` and needs no
Google credentials. It has no push or pull-request deployment trigger.

Initially inspect the default Pages URL returned by the deployment; for this
project it is expected to be `https://dm0.github.io/gdocs-scope-mcp/`, unless
account-wide custom-domain settings change it. Check the homepage, privacy and
terms links without logging in. The site must be substantial before the
is-a.dev registration request. Do not publish the entire repository root.

## 2. Obtain two public DNS challenges

These are verification strings for DNS, not OAuth tokens or client secrets.

1. In [Google Search Console](https://search.google.com/search-console), under
   a Google account that is an Owner/Editor of project `gdocs-scope-mcp`, add
   the Domain property `gdocs-scope-mcp.is-a.dev` without a scheme or path.
   Select TXT verification and copy the exact `google-site-verification=...`
   value. Adding the property is not proof of ownership; verification happens
   only after the DNS record is live. If Google instead requires ownership of
   the parent `is-a.dev`, stop and retain the exact error for investigation.
2. In your GitHub account Settings > Pages > Add a domain, enter
   `gdocs-scope-mcp.is-a.dev`. Copy the exact challenge hostname and value.
   The expected hostname is
   `_github-pages-challenge-dm0.gdocs-scope-mcp.is-a.dev`; use the actual value
   provided by GitHub if it differs.

Follow [Search Console verification](https://support.google.com/webmasters/answer/9008080?hl=en)
and [GitHub domain verification](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages).
The checks are independent and both records must remain in DNS.

## 3. Submit the is-a.dev requests

Fork [is-a-dev/register](https://github.com/is-a-dev/register) as `dm0` and
recheck the candidate's availability. Review the registry's current rules and
PR template. The following staged approach avoids directing web traffic at
GitHub until the domain is verified and claimed by the intended repository.
It relies on maintainers accepting an initial TXT-only verification stage;
record support does not guarantee approval of that registration request.

### Request A: domain registration and Google ownership record

Add `domains/gdocs-scope-mcp.json`:

```json
{
  "owner": {"username": "dm0"},
  "records": {
    "TXT": "REPLACE_WITH_COMPLETE_GOOGLE_SITE_VERIFICATION_VALUE"
  }
}
```

Suggested PR title:

> Register gdocs-scope-mcp.is-a.dev

Suggested PR body, in addition to the registry's required checklist:

> I maintain gdocs-scope-mcp, a non-commercial open-source development project
> that connects MCP-compatible AI assistants to Google Docs.
>
> Project: https://github.com/dm0/gdocs-scope-mcp
>
> Prepared website: REPLACE_WITH_THE_ACTUAL_PUBLIC_GITHUB_PAGES_URL
>
> This request registers the project domain with a Google Search Console
> ownership-verification TXT record. I will add the GitHub Pages ownership
> challenge next, then connect the verified domain to the existing project
> website using GitHub Pages A records. The temporary TXT-only stage avoids
> pointing an unclaimed domain at GitHub Pages.
>
> I am registering through my personal account dm0. The website and project
> are non-commercial. Contact: gdocs-scope-mcp@googlegroups.com.

If maintainers reject TXT-only registration, ask them about the phased setup
in the same request. An alternative is an approved combined A/TXT registration
after the intended Pages repository has accepted the custom-domain setting.
Do not point A records at an unclaimed Pages domain to work around a rejection.

After merge and DNS propagation, click Verify in Search Console. Keep the TXT.

### Request B: GitHub account domain-verification record

Once the parent registration is merged, add the nested file matching GitHub's
actual challenge. For the expected hostname, the filename is
`domains/_github-pages-challenge-dm0.gdocs-scope-mcp.json`:

```json
{
  "owner": {"username": "dm0"},
  "records": {
    "TXT": "REPLACE_WITH_GITHUB_PAGES_CHALLENGE_VALUE"
  }
}
```

Suggested PR title:

> Verify gdocs-scope-mcp.is-a.dev for GitHub Pages

Suggested PR body:

> Add the GitHub-issued DNS challenge for my registered project domain
> gdocs-scope-mcp.is-a.dev. The parent registration belongs to dm0. This record
> verifies the domain for the dm0 GitHub account before web DNS is activated.

After merge and propagation, complete verification in GitHub account
Settings > Pages. Keep the TXT record.

### Request C: activate website DNS

In `dm0/gdocs-scope-mcp` repository Settings > Pages, set Custom domain to
`gdocs-scope-mcp.is-a.dev`. Then update the existing root registration file,
preserving the real Google TXT value:

```json
{
  "owner": {"username": "dm0"},
  "records": {
    "A": [
      "185.199.108.153",
      "185.199.109.153",
      "185.199.110.153",
      "185.199.111.153"
    ],
    "TXT": "REPLACE_WITH_THE_EXISTING_COMPLETE_GOOGLE_SITE_VERIFICATION_VALUE"
  }
}
```

Suggested PR title:

> Connect gdocs-scope-mcp.is-a.dev to GitHub Pages

Suggested PR body:

> Connect my registered project domain to the existing GitHub Pages website
> for dm0/gdocs-scope-mcp. Domain verification is complete and the repository
> custom-domain setting is configured. Preserve both ownership-verification
> TXT records. The project remains non-commercial.

Recheck the addresses in [GitHub's DNS instructions](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)
before submitting. After merge, wait for DNS/certificate issuance and enable
Enforce HTTPS in Pages settings. Check all three pages on the custom domain.
Use the [is-a.dev Pages guide](https://docs.is-a.dev/guides/github-pages/) and
[record schema](https://docs.is-a.dev/domain-structure/) for registry details.
A records permit the Google TXT record at the same name; a CNAME does not.

## 4. Prepare the Google branding application

In project `gdocs-scope-mcp` [Branding](https://console.cloud.google.com/auth/branding?project=gdocs-scope-mcp),
use these values after the custom-domain pages are live and final:

| Field | Value |
| --- | --- |
| App name | `gdocs-scope-mcp` |
| Support email | `gdocs-scope-mcp@googlegroups.com` |
| Homepage | `https://gdocs-scope-mcp.is-a.dev/` |
| Privacy policy | `https://gdocs-scope-mcp.is-a.dev/privacy.html` |
| Terms | `https://gdocs-scope-mcp.is-a.dev/terms.html` |
| Authorized domain | `gdocs-scope-mcp.is-a.dev` |

Use monitored developer contacts as requested by the Console. The Search
Console verified owner must be associated with the Cloud project. Follow the
current [branding submission instructions](https://developers.google.com/identity/verification/authentication-verification).
Save the actual branding status and any reviewer feedback. A completed branding
check is separate from approval for sensitive/restricted data access.

## 5. Submit data-access review only after the open decisions are resolved

Leave the current four scope declarations intact for now: they match the
current code. The readiness audit proposes `drive.file` for selected mode and
`drive` alone for full mode. That reduction needs implementation and validation
before Console declarations or reviewer claims are changed.

Also resolve token-protection requirements, permitted MCP/AI-provider data use,
and whether the deployment requires a security assessment. Do not claim an
exemption because the executable runs locally. Do not submit the draft privacy
policy as a completed compliance statement or purchase an assessment yet.

Once those decisions are resolved, use Verification Center to prepare the
review for the actual final scopes. Proposed rationale for broad discovery,
subject to Google's review:

> The optional full-drive mode lets the user discover and search their existing
> Google Docs by title without first opening each document in Picker. It then
> reads and edits documents chosen through the MCP host. drive.file supports
> the separate selected-file workflow but cannot provide account-wide discovery
> of files that the application has not been granted. Broad access is disclosed
> during authorization, and agents cannot change the configured access mode.

Do not invent independent reasons for overlapping `drive.readonly` or
`documents` permissions. Prepare a synthetic-document demo showing mode
configuration, consent, listing/selection, a bounded edit and revocation. Match
the demo to the exact public revision and client being submitted.

Testing explains the current Verification Center message. Change publishing
status only as part of the ready-for-public-use sequence required by the
Console. Publishing status alone does not approve the brand or restricted
scopes; follow the current [restricted-scope process](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification).
Finish by checking authorization with an account outside the test-user list,
an authorized document operation and refresh after restarting a clean install.

## Evidence to return

Send the two public DNS challenge strings first so the local request files can
be finalized. Later retain PR links, verified-domain statuses, final public
URLs, Google review statuses and the public-user test result. Do not include
OAuth codes, access/refresh tokens or client-secret JSON in these reports.
