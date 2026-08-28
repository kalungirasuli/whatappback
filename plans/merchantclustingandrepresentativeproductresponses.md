## Plan: Merchant Clustering and Representative Product Responses

TL;DR
- Add a merchant-cluster result shape so search returns one representative product image per cluster and an attached list of high-scoring merchant matches.
- Apply a 0.4 score threshold for merchants recorded in a cluster and hide duplicate same-merchant matches.
- Preserve product-level related items while returning up to two additional related products.
- Save cluster metadata for result-code recall and use it when the buyer clicks interest to show merchant clusters for that product.

Steps
1. Analyze current search response shape and product formatting.
   - `src/api/routes/search.py` `_format_results`
   - `src/api/routes/chat.py` sections build and `messages` output
   - `src/workers/search_pipeline.py` search result generation

2. Define new cluster response model.
   - Add cluster payload shape that includes:
     - representative `product_id`
     - one representative image URL and primary image metadata
     - product name, category, price, brand, match score, match label
     - merchant cluster list with `merchant_id`, `business_name`, `location_lat`, `location_lng`, `phone_number`, and merchant-specific score
     - `merchant_count` and `cluster_score`
     - `related_products` list with up to two related representative products

3. Update search result processing to build clusters.
   - In `SearchPipeline` or helper service, group results by product similarity/cluster key.
   - Deduplicate by merchant and keep the highest-scoring product hit per merchant.
   - Only include merchants with score >= 0.4 in the cluster.
   - If a cluster has >30 merchants, return one representative image and a paginated merchant list.
   - If merchants are overly concentrated from the same seller, balance by limiting duplicates and selecting alternate high-score merchants.

4. Update search formatting and chat response builders.
   - Replace or augment `_format_results` in `src/api/routes/search.py` with cluster-aware formatting.
   - Modify `src/api/routes/chat.py` and `src/workers/nlu_router.py` logic to support cluster sections alongside existing result sections.
   - Ensure chat and search APIs preserve current behavior for existing non-clustered results.

5. Persist cluster metadata for result-code recall.
   - Extend `ResultCodeService.store()` to optionally save clustered product/merchant metadata or representative merchant IDs.
   - Update `src/api/routes/chat.py` result-code storage call to persist cluster-level sample output.
   - Ensure `src/api/routes/result_codes.py` and chat recall return the same cluster structure if appropriate.

6. Add interest-click merchant cluster endpoint.
   - Extend `src/api/routes/clients.py` express interest flow or add a new endpoint to return merchant clusters for a chosen product.
   - Use stored cluster metadata or regenerate cluster merchants for the selected product with the same 0.4 threshold.
   - Return a single representative image for the product and the matching merchant list.

7. Add pagination/opportunity distribution controls.
   - Add cluster pagination support in the merchant list response, likely with `page` and `size` query params.
   - In cluster generation, avoid overloading a single merchant by limiting one result per merchant in top merchant lists.
   - If there are many merchants for one product, choose merchants with the highest score while preserving geographic diversity if location data is available.

8. Add tests and validation.
   - Extend `tests/test_search_pipeline.py` with cluster-building tests and merchant de-duplication.
   - Add response shape tests for `src/api/routes/search.py` cluster formatting.
   - Add chat API tests for cluster sections and result-code recall behavior.
   - Add tests for interest-click merchant cluster endpoint.

Relevant files
- `src/api/routes/search.py`
- `src/api/routes/chat.py`
- `src/api/routes/clients.py`
- `src/api/routes/result_codes.py`
- `src/services/result_code_service.py`
- `src/workers/search_pipeline.py`
- `src/services/qdrant_service.py` (if cluster matching metadata or alternative vector grouping is needed)
- `src/domain/models.py` (review product/merchant/interest shapes)
- `tests/test_search_pipeline.py`
- `tests/test_api_search.py`
- `tests/test_api_chat.py`
- `tests/test_api_clients.py`

Verification
1. Run targeted unit tests for `SearchPipeline` cluster generation and `_format_results`.
2. Validate chat image search returns cluster sections with one representative product image and merchant list.
3. Verify result-code recall returns stored cluster metadata and not duplicate merchant-heavy product listings.
4. Confirm interest click endpoint returns merchant cluster details for a specific product.
5. Check pagination on merchant clusters behaves correctly and excludes merchants with score < 0.4.

Decisions
- Clusters will be built at response time from matching search results, not by changing the underlying product index.
- Merchant matches below score 0.4 are excluded from clusters.
- One representative image will be attached per cluster when merchant count is large, while keeping top two related products visible.
- Result codes will save cluster/representative product metadata rather than all raw product hits.

Further Considerations
1. We may need a canonical product grouping key beyond product_id if many merchants sell identical items. A later enhancement can use normalized `name+brand+category` or a dedicated product-family hash.
2. The UX should clearly distinguish product clusters from related products, so buyers understand they are choosing among merchant offers for the same item.
3. If merchants have identical product listings, ensure the cluster does not over-expose a single seller by limiting duplicate listings per merchant.
