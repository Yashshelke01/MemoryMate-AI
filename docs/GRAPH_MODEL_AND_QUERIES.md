\# MemoryMate AI — Graph Data Model and Cypher Queries



\## 1. Overview



MemoryMate AI uses FalkorDB as its graph database to store, organize, and retrieve personal memories.



The graph layer represents users, memories, and relationships between memories. It supports memory creation, retrieval, updating, deletion, keyword search, relationship traversal, and correction of previously stored information.



The implementation uses parameterized OpenCypher queries to separate query structure from user-supplied values.



\*\*Implementation source:\*\* `graph\_memory\_db/graph\_queries.py`



\## 2. Graph Data Model



The graph layer defines two node labels and two relationship types.



\### Node Labels



| Label    | Properties                                                                                                                                                                        | Purpose                                                   |

| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |

| `User`   | `user\_id`                                                                                                                                                                         | Identifies a user whose memories are stored in the graph. |

| `Memory` | `memory\_id`, `user\_id`, `content`, `category`, `subject`, `normalized\_subject`, `created\_at`, `updated\_at`, `source\_message\_id`, `source\_conversation\_id`, `provenance`, `status` | Represents a stored memory and its metadata.              |



\### Relationship Types



| Relationship | Direction                                   | Purpose                                                                                              |

| ------------ | ------------------------------------------- | ---------------------------------------------------------------------------------------------------- |

| `HAS\_MEMORY` | `(User)-\[:HAS\_MEMORY]->(Memory)`            | Connects a user to their memories.                                                                   |

| `RELATED\_TO` | `(Memory)-\[:RELATED\_TO {reason}]->(Memory)` | Connects two related memories and optionally describes the relationship using the `reason` property. |



\### Graph Structure



```text

(:User {user\_id})

&#x20;      |

&#x20;      | HAS\_MEMORY

&#x20;      v

(:Memory {memory\_id, user\_id, content, status})

&#x20;      |

&#x20;      | RELATED\_TO {reason}

&#x20;      v

(:Memory {memory\_id, user\_id, content, status})

```



A user can own multiple memories. Memories can also be connected to other memories using `RELATED\_TO` relationships.



\### Memory Properties



| Property                 | Description                                                                    |

| ------------------------ | ------------------------------------------------------------------------------ |

| `memory\_id`              | Unique identifier for a memory.                                                |

| `user\_id`                | Identifier of the user who owns the memory.                                    |

| `content`                | Stored memory text.                                                            |

| `category`               | Category assigned to the memory.                                               |

| `subject`                | Subject associated with the memory.                                            |

| `normalized\_subject`     | Normalized subject used for consistent matching.                               |

| `created\_at`             | Memory creation timestamp.                                                     |

| `updated\_at`             | Timestamp of the most recent supported update.                                 |

| `source\_message\_id`      | Identifier of the source message, or an empty string when absent.              |

| `source\_conversation\_id` | Identifier of the source conversation, or an empty string when absent.         |

| `provenance`             | JSON-serialized metadata describing the memory's origin or correction history. |

| `status`                 | Indicates whether a memory is `active` or `superseded`.                        |



The `provenance` JSON object can contain:



\* `kind`: the type of memory source.

\* `source\_text`: the original source text, when available.

\* `supersedes\_memory\_id`: the identifier of an earlier memory replaced by a correction.



The query helpers serialize provenance as JSON text because the graph layer stores it as a string property.



\## 3. Indexing



The graph layer defines indexes for frequently matched properties.



```cypher

CREATE INDEX FOR (u:User) ON (u.user\_id);



CREATE INDEX FOR (m:Memory) ON (m.memory\_id);



CREATE INDEX FOR (m:Memory) ON (m.user\_id);



CREATE INDEX FOR (m:Memory) ON (m.normalized\_subject);

```



These indexes are intended to improve lookup performance for users, memories, user ownership, and normalized subjects.



The implementation defines these index statements; successful creation depends on executing them against a compatible FalkorDB instance.



\## 4. Memory Creation



The `CREATE\_MEMORY\_QUERY` creates or matches a user and a memory, initializes memory properties when the memory is new, verifies ownership, and creates the ownership relationship.



```cypher

MERGE (u:User {user\_id: $user\_id})

MERGE (m:Memory {memory\_id: $memory\_id})

ON CREATE SET

&#x20; m.user\_id = $user\_id,

&#x20; m.content = $content,

&#x20; m.category = $category,

&#x20; m.subject = $subject,

&#x20; m.normalized\_subject = $normalized\_subject,

&#x20; m.created\_at = $created\_at,

&#x20; m.updated\_at = $updated\_at,

&#x20; m.source\_message\_id = $source\_message\_id,

&#x20; m.source\_conversation\_id = $source\_conversation\_id,

&#x20; m.provenance = $provenance,

&#x20; m.status = $status

WITH u, m

WHERE m.user\_id = $user\_id

MERGE (u)-\[:HAS\_MEMORY]->(m)

RETURN m

```



\### How it works



1\. Finds or creates the user node.

2\. Finds or creates the memory node using its identifier.

3\. Initializes the memory's properties when the node is created.

4\. Verifies that the memory belongs to the requested user.

5\. Creates the `HAS\_MEMORY` relationship.

6\. Returns the memory.



All values are passed through parameters instead of being interpolated into the query string.



\*\*Important:\*\* The query initializes properties only on creation. Existing memory properties are not overwritten by this query's `ON CREATE SET` clause.



\## 5. Retrieving a Specific Memory



The `GET\_MEMORY\_QUERY` retrieves a memory owned by a particular user.



```cypher

MATCH (u:User {user\_id: $user\_id})-\[:HAS\_MEMORY]->

&#x20;     (m:Memory {memory\_id: $memory\_id})

WHERE m.user\_id = $user\_id

RETURN m

LIMIT 1

```



The query matches both the user's ownership relationship and the memory identifier. It also verifies the memory's `user\_id` property.



\## 6. Listing and Counting Active Memories



\### Count Active Memories



```cypher

MATCH (u:User {user\_id: $user\_id})-\[:HAS\_MEMORY]->(m:Memory)

WHERE m.user\_id = $user\_id AND m.status = 'active'

RETURN count(m) AS total

```



This query returns the number of active memories owned by the specified user.



\### List Active Memories



```cypher

MATCH (u:User {user\_id: $user\_id})-\[:HAS\_MEMORY]->(m:Memory)

WHERE m.user\_id = $user\_id AND m.status = 'active'

RETURN m

ORDER BY m.updated\_at DESC, m.memory\_id ASC

SKIP $offset

LIMIT $limit

```



The query supports pagination through `SKIP` and `LIMIT`. Results are ordered by update time, with the memory identifier providing a secondary ordering.



\## 7. Finding Memories by Subject



The `FIND\_ACTIVE\_BY\_SUBJECT\_QUERY` matches active memories using their normalized subject.



```cypher

MATCH (u:User {user\_id: $user\_id})-\[:HAS\_MEMORY]->(m:Memory)

WHERE m.user\_id = $user\_id

&#x20; AND m.status = 'active'

&#x20; AND m.normalized\_subject = $normalized\_subject

&#x20; AND ($category = '' OR m.category = $category)

RETURN m

ORDER BY m.updated\_at DESC, m.memory\_id ASC

LIMIT $limit

```



The category filter is optional. When `$category` is an empty string, the query does not restrict results by category.



\## 8. Updating a Memory



The `UPDATE\_MEMORY\_QUERY` updates the content and subject-related fields of an active memory owned by the specified user.



```cypher

MATCH (u:User {user\_id: $user\_id})-\[:HAS\_MEMORY]->

&#x20;     (m:Memory {memory\_id: $memory\_id})

WHERE m.user\_id = $user\_id AND m.status = 'active'

SET m.content = $content,

&#x20;   m.category = $category,

&#x20;   m.subject = $subject,

&#x20;   m.normalized\_subject = $normalized\_subject,

&#x20;   m.updated\_at = $updated\_at

RETURN m

```



The query does not update every memory property. For example, creation time and provenance are not changed by this query.



\## 9. Correcting a Memory



The `SUPERSEDE\_MEMORY\_QUERY` supports conversational correction by marking an existing active memory as superseded and creating a replacement memory.



```cypher

MATCH (u:User {user\_id: $user\_id})-\[:HAS\_MEMORY]->

&#x20;     (old:Memory {memory\_id: $old\_memory\_id})

WHERE old.user\_id = $user\_id AND old.status = 'active'

SET old.status = 'superseded',

&#x20;   old.updated\_at = $updated\_at

MERGE (new\_m:Memory {memory\_id: $memory\_id})

ON CREATE SET

&#x20; new\_m.user\_id = $user\_id,

&#x20; new\_m.content = $content,

&#x20; new\_m.category = $category,

&#x20; new\_m.subject = $subject,

&#x20; new\_m.normalized\_subject = $normalized\_subject,

&#x20; new\_m.created\_at = $created\_at,

&#x20; new\_m.updated\_at = $updated\_at,

&#x20; new\_m.source\_message\_id = $source\_message\_id,

&#x20; new\_m.source\_conversation\_id = $source\_conversation\_id,

&#x20; new\_m.provenance = $provenance,

&#x20; new\_m.status = 'active'

WITH u, old, new\_m

WHERE new\_m.user\_id = $user\_id

MERGE (u)-\[:HAS\_MEMORY]->(new\_m)

RETURN new\_m, old

```



\### Why this matters



Instead of simply overwriting the old memory, the query preserves the earlier memory node and changes its status to `superseded`.



The replacement memory can record the previous memory's identifier in its provenance metadata using `supersedes\_memory\_id`.



This approach preserves the earlier memory record for potential historical inspection while allowing the replacement to be treated as active.



The query is submitted as one graph query execution. Whether it provides full transactional guarantees depends on the database's execution semantics and should not be inferred solely from the single-query structure.



\## 10. Deleting a Memory



The `DELETE\_MEMORY\_QUERY` deletes the specified user's memory and its incident `RELATED\_TO` relationships.



```cypher

MATCH (u:User {user\_id: $user\_id})-\[:HAS\_MEMORY]->

&#x20;     (m:Memory {memory\_id: $memory\_id})

WHERE m.user\_id = $user\_id

OPTIONAL MATCH (m)-\[r:RELATED\_TO]-()

DELETE r

WITH DISTINCT m

DETACH DELETE m

RETURN count(m) AS deleted

```



The query:



1\. Matches a memory through the specified user's ownership relationship.

2\. Verifies the memory's owner.

3\. Deletes its `RELATED\_TO` relationships.

4\. Deletes the memory node.

5\. Returns the deletion count.



The query does not explicitly delete the `User` node.



\## 11. Keyword-Based Memory Search



\### Single-Term Search



The `SEARCH\_MEMORIES\_BY\_TERM\_QUERY` searches active memories by content, subject, normalized subject, or category.



```cypher

MATCH (u:User {user\_id: $user\_id})-\[:HAS\_MEMORY]->(m:Memory)

WHERE m.user\_id = $user\_id

&#x20; AND m.status = 'active'

&#x20; AND (

&#x20;   toLower(m.content) CONTAINS toLower($term)

&#x20;   OR toLower(m.subject) CONTAINS toLower($term)

&#x20;   OR m.normalized\_subject CONTAINS toLower($term)

&#x20;   OR toLower(m.category) = toLower($term)

&#x20; )

RETURN m

ORDER BY m.updated\_at DESC, m.memory\_id ASC

LIMIT $limit

```



The query uses case-normalized comparisons for several fields and supports partial matching for content and subject.



Category matching uses equality rather than substring matching.



\### Multi-Term Search



The `SEARCH\_MEMORIES\_BY\_TERMS\_QUERY` uses `UNWIND` to process a list of search terms.



```cypher

UNWIND $terms AS term

MATCH (u:User {user\_id: $user\_id})-\[:HAS\_MEMORY]->(m:Memory)

WHERE m.user\_id = $user\_id

&#x20; AND m.status = 'active'

&#x20; AND (

&#x20;   toLower(m.content) CONTAINS toLower(term)

&#x20;   OR toLower(m.subject) CONTAINS toLower(term)

&#x20;   OR m.normalized\_subject CONTAINS toLower(term)

&#x20;   OR toLower(m.category) = toLower(term)

&#x20; )

RETURN DISTINCT m

ORDER BY m.updated\_at DESC, m.memory\_id ASC

LIMIT $limit

```



`UNWIND` expands the provided list into individual terms. `RETURN DISTINCT` prevents the same memory from being returned multiple times when it matches more than one term.



This is parameterized keyword search; it should not be described as vector search or embedding-based semantic search unless another part of the application implements those methods.



\## 12. Retrieving Related Memories



The `RELATED\_MEMORIES\_QUERY` performs a bounded one-hop traversal over `RELATED\_TO` relationships.



```cypher

MATCH (u:User {user\_id: $user\_id})-\[:HAS\_MEMORY]->

&#x20;     (m:Memory {memory\_id: $memory\_id})

WHERE m.user\_id = $user\_id AND m.status = 'active'

MATCH (m)-\[r:RELATED\_TO]-(related:Memory)<-\[:HAS\_MEMORY]-(u)

WHERE related.user\_id = $user\_id

&#x20; AND related.status = 'active'

&#x20; AND related.memory\_id <> m.memory\_id

RETURN DISTINCT related, r.reason AS relationship

ORDER BY related.updated\_at DESC, related.memory\_id ASC

LIMIT $limit

```



The query:



1\. Finds the requested active memory.

2\. Traverses one `RELATED\_TO` relationship in either direction.

3\. Restricts related memories to the same user.

4\. Excludes the starting memory.

5\. Returns distinct related memories and the relationship reason.

6\. Limits the number of results.



This is graph traversal, not an unbounded graph exploration algorithm.



\## 13. Creating Relationships Between Memories



The `CREATE\_RELATED\_TO\_QUERY` creates or matches a directed relationship between two distinct active memories belonging to the same user.



```cypher

MATCH (u:User {user\_id: $user\_id})-\[:HAS\_MEMORY]->(m1:Memory {memory\_id: $source\_id})

MATCH (u)-\[:HAS\_MEMORY]->(m2:Memory {memory\_id: $target\_id})

WHERE m1.user\_id = $user\_id

&#x20; AND m2.user\_id = $user\_id

&#x20; AND m1.status = 'active'

&#x20; AND m2.status = 'active'

&#x20; AND m1.memory\_id <> m2.memory\_id

MERGE (m1)-\[r:RELATED\_TO]->(m2)

SET r.reason = $reason

RETURN count(r) AS created

```



`MERGE` avoids creating another matching relationship with the same direction and endpoints. The relationship's `reason` property is set to the supplied value.



The relationship is directed in storage. The related-memory retrieval query can traverse relationships in either direction.



\## 14. Listing Graph Relationships



The `LIST\_RELATIONSHIPS\_QUERY` retrieves relationships between active memories associated with the requested user.



```cypher

MATCH (u:User {user\_id: $user\_id})-\[:HAS\_MEMORY]->(m1:Memory)-\[r:RELATED\_TO]->(m2:Memory)<-\[:HAS\_MEMORY]-(u)

WHERE m1.user\_id = $user\_id

&#x20; AND m2.user\_id = $user\_id

&#x20; AND m1.status = 'active'

&#x20; AND m2.status = 'active'

RETURN m1.memory\_id AS source,

&#x20;      m2.memory\_id AS target,

&#x20;      r.reason AS reason

ORDER BY m1.memory\_id ASC, m2.memory\_id ASC

LIMIT $limit

```



The query returns graph edges as source-target pairs with a reason property. This representation can support graph data visualization or inspection in the application.



\## 15. Health Check



The graph layer defines a simple health-check query:



```cypher

RETURN 1 AS ok

```



It can be used to check whether a graph query can execute successfully against the connected database.



A successful query alone does not prove that all application services are healthy.



\## 16. Parameterization and Security



The query implementation uses parameters such as `$user\_id`, `$memory\_id`, `$content`, and `$limit` instead of interpolating user-provided values into query strings.



A helper validates parameter names and restricts parameter values to supported scalar or scalar-list types.



The memory write helper also serializes provenance metadata into JSON text and normalizes optional source identifiers to empty strings when absent.



These techniques help reduce query-injection risk and keep graph property values compatible with the application's storage conventions.



User-scoped queries also match the `User` node and check memory ownership. These safeguards should be combined with backend authentication and authorization checks.



\## 17. Graph Algorithms and Retrieval Strategy



The inspected query module implements several graph operations:



\* Node creation and matching using `MERGE`.

\* Relationship creation and matching using `MERGE`.

\* One-hop relationship traversal.

\* User-scoped graph filtering.

\* Keyword-based memory search.

\* Distinct-result filtering for multi-term search.

\* Timestamp-based result ordering.

\* Memory supersession for conversational correction.



The inspected file does not establish that algorithms such as PageRank, community detection, shortest-path analysis, or vector similarity search are implemented. Such features should only be documented if confirmed in the actual code.



\## 18. Summary



FalkorDB provides MemoryMate AI with a graph-based representation of users, memories, and relationships between memories.



The graph layer supports creating, retrieving, updating, superseding, and deleting memories, along with subject-based search, keyword retrieval, and bounded relationship traversal.



Parameterized queries and user ownership checks are important parts of the implementation. Together, these operations provide a foundation for connected personal memory retrieval.



\*\*Source of truth:\*\* `graph\_memory\_db/graph\_queries.py`. Confirm the backend query module and the runtime behavior before treating this document as a complete description of every graph operation in the application.



