# 0064: Sitemap XML is parsed defensively and recursively within fixed limits

Status: implemented for review

The existing lxml dependency parses only bounded in-memory bytes with entity resolution, DTD loading, network access, recovery, and huge-tree mode disabled. Byte preflight rejects DOCTYPE and entity declarations. Standard `urlset` and `sitemapindex` roots are supported; namespace and content-type imperfections are warnings when the payload is otherwise safe XML.

Indexes expand breadth-first in parent order. Requested and final identities stop repeats, aliases, and loops. Default limits are 50,000 URL entries, 50,000 child references, 100 documents, depth 3, and 250,000 total unique URLs. Limit and child failures preserve partial durable evidence.
