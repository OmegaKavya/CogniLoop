STATIC_CHEAT_SHEETS = {
    'os': {
        'title': 'Operating Systems Rapid Revision',
        'estimated_minutes': 5,
        'core': [
            'Kernel is the privileged core that schedules processes and manages memory/devices.',
            'Process = program in execution; thread = lightweight execution unit inside a process.',
            'CPU scheduling goals: throughput, response time, fairness, and utilization.',
            'Memory management basics: paging, virtual memory, page faults, and replacement.',
            'Concurrency primitives: mutex, semaphore, monitor; use to avoid race conditions.',
            'Deadlock conditions (Coffman): mutual exclusion, hold-and-wait, no preemption, circular wait.'
        ],
        'pitfalls': [
            'Confusing process context switch with thread switch overhead.',
            'Mixing starvation and deadlock — they are not the same failure mode.',
            'Ignoring critical-section boundaries in synchronization questions.'
        ],
        'drills': [
            'Explain FCFS vs Round Robin in 2 lines with one use-case each.',
            'Write one scenario where paging helps and one where it hurts.',
            'State one deadlock prevention strategy and trade-off.'
        ]
    },
    'ds': {
        'title': 'Data Structures Rapid Revision',
        'estimated_minutes': 5,
        'core': [
            'Pick structure by operation profile: lookup, insert, delete, traversal.',
            'Array: O(1) index access, costly middle insert/delete.',
            'Linked list: easy insert/delete with pointer, no O(1) random access.',
            'Stack (LIFO) and queue (FIFO) power many algorithmic patterns.',
            'Trees support hierarchical queries; BST/search costs depend on balance.',
            'Graphs require choosing BFS/DFS based on shortest-path and traversal needs.'
        ],
        'pitfalls': [
            'Using recursion without checking base conditions and stack depth.',
            'Assuming average-case complexity when question asks worst-case.',
            'Forgetting visited tracking in graph traversal problems.'
        ],
        'drills': [
            'Give one real-world stack and queue example each.',
            'Compare BST vs hash table for dynamic lookup workloads.',
            'List BFS and DFS time complexity in terms of V and E.'
        ]
    },
    'dbms': {
        'title': 'DBMS Rapid Revision',
        'estimated_minutes': 5,
        'core': [
            'Primary key uniquely identifies rows; foreign key enforces relationships.',
            'Normalization reduces redundancy and update anomalies.',
            'Transactions obey ACID for reliable concurrent operations.',
            'Indexes speed reads but add write overhead and storage cost.',
            'JOIN types determine row inclusion logic across tables.',
            'Isolation levels trade strict consistency for performance.'
        ],
        'pitfalls': [
            'Confusing candidate key with primary key selection.',
            'Applying too many indexes on write-heavy tables.',
            'Missing NULL behavior in joins and conditions.'
        ],
        'drills': [
            'Explain INNER JOIN vs LEFT JOIN with one mini example.',
            'State one anomaly fixed by 3NF.',
            'Give one case where denormalization is acceptable.'
        ]
    },
    'cn': {
        'title': 'Computer Networks Rapid Revision',
        'estimated_minutes': 5,
        'core': [
            'Layered design separates concerns: link, network, transport, application.',
            'IP handles addressing/routing; TCP/UDP handle end-to-end delivery behavior.',
            'TCP offers reliability, flow + congestion control; UDP favors low latency.',
            'Routing decides path between networks; switching forwards within local network.',
            'Common protocols: HTTP/HTTPS, DNS, DHCP, ARP, ICMP.',
            'Subnetting partitions address space for scalable routing and control.'
        ],
        'pitfalls': [
            'Mixing OSI conceptual layers with exact protocol placement.',
            'Confusing flow control with congestion control.',
            'Ignoring handshake/teardown sequence in TCP questions.'
        ],
        'drills': [
            'Contrast TCP and UDP in one sentence each.',
            'Trace packet flow from browser request to server response.',
            'Define subnet mask purpose in plain language.'
        ]
    }
}

# Topic-specific submodule definitions with real CS curriculum content
# Each module has: title, objective, exam_angle, start_sec, end_sec, checkpoints
SUBMODULE_DEFINITIONS = {
    'os': [
        {
            "title": "Process & Thread Lifecycle",
            "objective": "Understand how processes are created, scheduled, and terminated — and how threads differ from processes.",
            "exam_angle": "🎯 GATE Tip: Process state diagrams and context switch overhead appear in almost every OS paper.",
            "start_sec": 0,
            "end_sec": 420,
            "checkpoints": [
                {
                    "id": "os-cp1-1", "trigger_pct": 30,
                    "question": "A process moves from Running to Waiting state. What is the most likely cause?",
                    "options": ["It requested an I/O operation", "It was preempted by the scheduler", "It completed execution", "A higher-priority process arrived"],
                    "correct_index": 0,
                    "explanation": "Running → Waiting happens on I/O requests. Preemption causes Running → Ready."
                },
                {
                    "id": "os-cp1-2", "trigger_pct": 65,
                    "question": "Why is thread context switching cheaper than process context switching?",
                    "options": ["Threads share the same address space and page tables", "Threads have their own memory space", "Threads don't use the CPU", "Threads skip OS scheduling"],
                    "correct_index": 0,
                    "explanation": "Threads within the same process share memory mappings, so the OS doesn't need to reload page tables."
                },
                {
                    "id": "os-cp1-3", "trigger_pct": 85,
                    "question": "Which scheduling algorithm can cause starvation of low-priority processes?",
                    "options": ["Priority Scheduling", "Round Robin", "FCFS", "Shortest Job First (non-preemptive)"],
                    "correct_index": 0,
                    "explanation": "Priority Scheduling starves low-priority processes if high-priority ones keep arriving."
                }
            ]
        },
        {
            "title": "Virtual Memory & Page Replacement",
            "objective": "Master paging, virtual address translation, page faults, and replacement policies like LRU and FIFO.",
            "exam_angle": "🎯 GATE Tip: Numerical questions on page fault counts with reference strings are extremely common.",
            "start_sec": 420,
            "end_sec": 900,
            "checkpoints": [
                {
                    "id": "os-cp2-1", "trigger_pct": 30,
                    "question": "In demand paging, when does a page fault occur?",
                    "options": ["A referenced page is not in physical memory", "The page table is full", "The CPU runs out of registers", "The disk is too slow"],
                    "correct_index": 0,
                    "explanation": "A page fault is triggered when the MMU can't find the referenced page in the TLB or page table (page not in RAM)."
                },
                {
                    "id": "os-cp2-2", "trigger_pct": 65,
                    "question": "Belady's anomaly means that adding more frames can increase page faults. Which algorithm suffers from this?",
                    "options": ["FIFO", "LRU", "Optimal", "Clock"],
                    "correct_index": 0,
                    "explanation": "FIFO exhibits Belady's anomaly. LRU and Optimal do not."
                },
                {
                    "id": "os-cp2-3", "trigger_pct": 85,
                    "question": "Thrashing occurs when a process spends more time page faulting than executing. What is the primary cause?",
                    "options": ["Too many processes competing for too few frames", "Too many CPU cores", "Page table is stored in ROM", "No virtual memory is enabled"],
                    "correct_index": 0,
                    "explanation": "Thrashing is caused by insufficient physical memory frames relative to working set size."
                }
            ]
        },
        {
            "title": "Synchronisation, Deadlock & IPC",
            "objective": "Understand race conditions, critical sections, semaphores, monitors, and all four Coffman deadlock conditions.",
            "exam_angle": "🎯 GATE Tip: Deadlock detection questions often ask you to identify the missing Coffman condition.",
            "start_sec": 900,
            "end_sec": None,
            "checkpoints": [
                {
                    "id": "os-cp3-1", "trigger_pct": 30,
                    "question": "Which Coffman condition can be directly prevented by allowing preemption of resources?",
                    "options": ["No Preemption", "Circular Wait", "Hold and Wait", "Mutual Exclusion"],
                    "correct_index": 0,
                    "explanation": "Eliminating 'No Preemption' means resources can be forcibly taken, preventing deadlock."
                },
                {
                    "id": "os-cp3-2", "trigger_pct": 65,
                    "question": "A semaphore initialized to 1 and used for mutual exclusion is called a:",
                    "options": ["Binary semaphore (mutex)", "Counting semaphore", "Spinlock", "Monitor"],
                    "correct_index": 0,
                    "explanation": "A binary semaphore with value 0 or 1 used for mutual exclusion is functionally a mutex."
                },
                {
                    "id": "os-cp3-3", "trigger_pct": 85,
                    "question": "What distinguishes a monitor from a semaphore?",
                    "options": ["Monitor enforces mutual exclusion automatically; semaphore requires explicit lock/unlock", "Semaphore is faster than a monitor", "Monitor can only be used in user space", "Semaphore prevents all deadlocks automatically"],
                    "correct_index": 0,
                    "explanation": "Monitors encapsulate shared data and enforce mutual exclusion by design, reducing programmer error vs raw semaphores."
                }
            ]
        }
    ],
    'ds': [
        {
            "title": "Linear Structures & Complexity Analysis",
            "objective": "Master arrays, linked lists, stacks, queues, and how to choose the right structure based on operation costs.",
            "exam_angle": "🎯 GATE Tip: Time complexity questions often compare array vs linked list for insert/delete at arbitrary positions.",
            "start_sec": 0,
            "end_sec": 420,
            "checkpoints": [
                {
                    "id": "ds-cp1-1", "trigger_pct": 30,
                    "question": "What is the time complexity of inserting an element at the beginning of a singly linked list?",
                    "options": ["O(1)", "O(n)", "O(log n)", "O(n²)"],
                    "correct_index": 0,
                    "explanation": "Inserting at the head of a linked list only requires updating the head pointer — O(1)."
                },
                {
                    "id": "ds-cp1-2", "trigger_pct": 65,
                    "question": "Which data structure is most suitable for implementing function call recursion in programming languages?",
                    "options": ["Stack", "Queue", "Heap", "Graph"],
                    "correct_index": 0,
                    "explanation": "Recursion uses a call stack (LIFO) — each function call pushes a frame, return pops it."
                },
                {
                    "id": "ds-cp1-3", "trigger_pct": 85,
                    "question": "A deque (double-ended queue) generalises both stack and queue. Which operation is NOT O(1) for a deque?",
                    "options": ["Search by value", "Insert at front", "Delete from rear", "Insert at rear"],
                    "correct_index": 0,
                    "explanation": "All insert/delete at ends are O(1) for deques. Search requires O(n) traversal."
                }
            ]
        },
        {
            "title": "Trees, BSTs & Balanced Structures",
            "objective": "Understand binary trees, BST operations, AVL rotations, heaps, and tree traversal patterns.",
            "exam_angle": "🎯 GATE Tip: BST worst-case height (skewed tree = O(n)) vs AVL guaranteed O(log n) is a classic exam contrast.",
            "start_sec": 420,
            "end_sec": 900,
            "checkpoints": [
                {
                    "id": "ds-cp2-1", "trigger_pct": 30,
                    "question": "What is the worst-case time complexity of search in an unbalanced Binary Search Tree?",
                    "options": ["O(n)", "O(log n)", "O(1)", "O(n log n)"],
                    "correct_index": 0,
                    "explanation": "A skewed BST degenerates to a linked list — search becomes O(n) in the worst case."
                },
                {
                    "id": "ds-cp2-2", "trigger_pct": 65,
                    "question": "In a max-heap, which property must hold for every node?",
                    "options": ["A node's value ≥ both its children's values", "A node's value ≤ both its children's values", "Left child > right child always", "All leaf nodes have equal values"],
                    "correct_index": 0,
                    "explanation": "Max-heap property: parent ≥ children. This ensures the maximum element is always at the root."
                },
                {
                    "id": "ds-cp2-3", "trigger_pct": 85,
                    "question": "Which traversal of a BST visits nodes in sorted (ascending) order?",
                    "options": ["Inorder (Left → Root → Right)", "Preorder (Root → Left → Right)", "Postorder (Left → Right → Root)", "Level-order (BFS)"],
                    "correct_index": 0,
                    "explanation": "Inorder traversal of a BST always produces sorted output due to the BST ordering property."
                }
            ]
        },
        {
            "title": "Graphs, Hashing & Algorithm Design",
            "objective": "Apply BFS/DFS, shortest path algorithms, and hash table design with collision resolution strategies.",
            "exam_angle": "🎯 GATE Tip: Dijkstra vs Bellman-Ford trade-offs (negative edges, complexity) appear frequently.",
            "start_sec": 900,
            "end_sec": None,
            "checkpoints": [
                {
                    "id": "ds-cp3-1", "trigger_pct": 30,
                    "question": "Why can't Dijkstra's algorithm handle graphs with negative edge weights?",
                    "options": ["It assumes all relaxations are final once a node is visited", "It uses BFS which doesn't support weights", "It only works on trees", "It requires the graph to be directed"],
                    "correct_index": 0,
                    "explanation": "Dijkstra marks nodes as 'settled'. A negative edge could make a settled node reachable for cheaper, violating this assumption."
                },
                {
                    "id": "ds-cp3-2", "trigger_pct": 65,
                    "question": "In open addressing (linear probing), what happens when the hash table becomes very full?",
                    "options": ["Clustering increases, making search degrade toward O(n)", "Performance improves due to cache locality", "Collisions become impossible", "The table automatically resizes"],
                    "correct_index": 0,
                    "explanation": "Linear probing causes primary clustering — long runs of occupied slots degrade average search time."
                },
                {
                    "id": "ds-cp3-3", "trigger_pct": 85,
                    "question": "Which algorithm finds the Minimum Spanning Tree by always picking the globally cheapest edge that doesn't form a cycle?",
                    "options": ["Kruskal's Algorithm", "Prim's Algorithm", "Dijkstra's Algorithm", "Bellman-Ford"],
                    "correct_index": 0,
                    "explanation": "Kruskal's sorts all edges by weight and greedily adds the cheapest that doesn't form a cycle (uses Union-Find)."
                }
            ]
        }
    ],
    'dbms': [
        {
            "title": "Relational Model, Keys & SQL Fundamentals",
            "objective": "Understand relational algebra, key types, SQL joins, and aggregate functions with GROUP BY and HAVING.",
            "exam_angle": "🎯 GATE Tip: Relational algebra expressions and SQL query output prediction are near-guaranteed exam questions.",
            "start_sec": 0,
            "end_sec": 420,
            "checkpoints": [
                {
                    "id": "db-cp1-1", "trigger_pct": 30,
                    "question": "What distinguishes a candidate key from a primary key?",
                    "options": ["A relation can have multiple candidate keys; only one is chosen as primary key", "Candidate keys allow NULL values", "Primary keys are not unique", "Candidate keys can have duplicate values"],
                    "correct_index": 0,
                    "explanation": "All candidate keys are unique and minimal. The DBA picks one to be the primary key; the rest are alternate keys."
                },
                {
                    "id": "db-cp1-2", "trigger_pct": 65,
                    "question": "A LEFT OUTER JOIN between tables A and B returns:",
                    "options": ["All rows from A, with NULLs for non-matching rows in B", "Only matching rows from both tables", "All rows from both A and B", "All rows from B, with NULLs for non-matching rows in A"],
                    "correct_index": 0,
                    "explanation": "LEFT JOIN keeps all rows from the left table and fills unmatched right-side columns with NULL."
                },
                {
                    "id": "db-cp1-3", "trigger_pct": 85,
                    "question": "What is the difference between WHERE and HAVING in SQL?",
                    "options": ["WHERE filters rows before grouping; HAVING filters groups after aggregation", "HAVING filters rows before grouping; WHERE filters after", "Both are identical in function", "WHERE works only with JOINs"],
                    "correct_index": 0,
                    "explanation": "WHERE operates on individual rows before GROUP BY. HAVING filters the resulting groups after aggregation."
                }
            ]
        },
        {
            "title": "Normalisation & Database Design",
            "objective": "Apply functional dependencies, identify anomalies, and normalise relations to 1NF, 2NF, 3NF, and BCNF.",
            "exam_angle": "🎯 GATE Tip: Given a relation and FDs, finding the highest normal form it satisfies is a classic 2-mark question.",
            "start_sec": 420,
            "end_sec": 900,
            "checkpoints": [
                {
                    "id": "db-cp2-1", "trigger_pct": 30,
                    "question": "A relation is in 2NF if it is in 1NF and:",
                    "options": ["No non-prime attribute is partially dependent on any candidate key", "No transitive dependencies exist", "All attributes are multivalued", "The primary key has only one attribute"],
                    "correct_index": 0,
                    "explanation": "2NF eliminates partial dependencies — every non-prime attribute must depend on the whole key, not part of it."
                },
                {
                    "id": "db-cp2-2", "trigger_pct": 65,
                    "question": "Which anomaly occurs when updating one tuple's data requires updating multiple tuples to maintain consistency?",
                    "options": ["Update anomaly", "Insertion anomaly", "Deletion anomaly", "Key anomaly"],
                    "correct_index": 0,
                    "explanation": "Update anomalies arise from redundancy — the same fact stored in multiple rows must be updated everywhere consistently."
                },
                {
                    "id": "db-cp2-3", "trigger_pct": 85,
                    "question": "BCNF is stricter than 3NF. Which condition makes a relation in 3NF but NOT in BCNF?",
                    "options": ["A non-trivial FD X→Y where X is not a superkey, but Y is a prime attribute", "A transitive dependency on a non-prime attribute", "Two candidate keys with identical attributes", "A multivalued dependency exists"],
                    "correct_index": 0,
                    "explanation": "3NF allows FDs where the determinant isn't a superkey if the dependent is a prime attribute. BCNF prohibits this."
                }
            ]
        },
        {
            "title": "Transactions, Concurrency & Recovery",
            "objective": "Master ACID properties, isolation levels, concurrency control protocols, and crash recovery mechanisms.",
            "exam_angle": "🎯 GATE Tip: Serializability of schedules (conflict vs view) and lock-based protocol questions are very common.",
            "start_sec": 900,
            "end_sec": None,
            "checkpoints": [
                {
                    "id": "db-cp3-1", "trigger_pct": 30,
                    "question": "Which ACID property ensures that once a transaction commits, its changes survive system crashes?",
                    "options": ["Durability", "Atomicity", "Consistency", "Isolation"],
                    "correct_index": 0,
                    "explanation": "Durability guarantees committed data is permanently saved, typically via write-ahead logging (WAL)."
                },
                {
                    "id": "db-cp3-2", "trigger_pct": 65,
                    "question": "Two transactions are in conflict if they access the same data item and:",
                    "options": ["At least one of them is a write operation", "Both are read operations", "They run on different CPUs", "They access different tables"],
                    "correct_index": 0,
                    "explanation": "Read-Read is non-conflicting. Read-Write and Write-Write on the same item are conflicts."
                },
                {
                    "id": "db-cp3-3", "trigger_pct": 85,
                    "question": "The 'dirty read' problem occurs at which isolation level?",
                    "options": ["Read Uncommitted", "Read Committed", "Repeatable Read", "Serializable"],
                    "correct_index": 0,
                    "explanation": "Read Uncommitted allows reading uncommitted (dirty) data from other transactions — the lowest isolation level."
                }
            ]
        }
    ],
    'cn': [
        {
            "title": "Network Architecture & Addressing",
            "objective": "Understand OSI vs TCP/IP layering, IP addressing, subnetting, and ARP/ICMP roles.",
            "exam_angle": "🎯 GATE Tip: Subnetting calculations (hosts per subnet, network address, broadcast) are standard numerical questions.",
            "start_sec": 0,
            "end_sec": 420,
            "checkpoints": [
                {
                    "id": "cn-cp1-1", "trigger_pct": 30,
                    "question": "In the OSI model, which layer is responsible for logical addressing and routing between networks?",
                    "options": ["Network Layer (Layer 3)", "Data Link Layer (Layer 2)", "Transport Layer (Layer 4)", "Session Layer (Layer 5)"],
                    "correct_index": 0,
                    "explanation": "The Network Layer handles IP addressing and routing (forwarding packets across networks)."
                },
                {
                    "id": "cn-cp1-2", "trigger_pct": 65,
                    "question": "A subnet mask of /26 means how many host addresses are available per subnet?",
                    "options": ["62", "64", "126", "30"],
                    "correct_index": 0,
                    "explanation": "/26 leaves 6 host bits: 2⁶ = 64 total, minus network and broadcast = 62 usable hosts."
                },
                {
                    "id": "cn-cp1-3", "trigger_pct": 85,
                    "question": "ARP (Address Resolution Protocol) maps which two types of addresses?",
                    "options": ["IP address to MAC address", "MAC address to DNS name", "Port number to IP address", "IP address to domain name"],
                    "correct_index": 0,
                    "explanation": "ARP resolves an IP address to the corresponding MAC (hardware) address on a local network."
                }
            ]
        },
        {
            "title": "Transport Layer: TCP vs UDP Deep Dive",
            "objective": "Master TCP's 3-way handshake, flow control (sliding window), congestion control, and when to choose UDP.",
            "exam_angle": "🎯 GATE Tip: TCP sequence number and acknowledgement number calculations appear in numerical questions.",
            "start_sec": 420,
            "end_sec": 900,
            "checkpoints": [
                {
                    "id": "cn-cp2-1", "trigger_pct": 30,
                    "question": "In TCP's 3-way handshake, what does the server send in the second step?",
                    "options": ["SYN-ACK", "SYN", "ACK", "FIN-ACK"],
                    "correct_index": 0,
                    "explanation": "Client sends SYN → Server replies SYN-ACK → Client sends ACK. This establishes the TCP connection."
                },
                {
                    "id": "cn-cp2-2", "trigger_pct": 65,
                    "question": "What is the purpose of TCP's sliding window mechanism?",
                    "options": ["Flow control — limits sender rate to receiver's buffer capacity", "Congestion control — detects network overload", "Error detection — checksums incoming packets", "Routing — selects the best network path"],
                    "correct_index": 0,
                    "explanation": "The sliding window controls how many bytes can be sent before requiring an ACK, matching sender rate to receiver capacity."
                },
                {
                    "id": "cn-cp2-3", "trigger_pct": 85,
                    "question": "Which application is best suited for UDP over TCP?",
                    "options": ["Live video streaming where some packet loss is acceptable", "Online banking transactions", "Email delivery", "File download with integrity guarantee"],
                    "correct_index": 0,
                    "explanation": "UDP's low latency is preferred for real-time media. Banking/files need TCP's reliability guarantees."
                }
            ]
        },
        {
            "title": "Application Layer & Routing Protocols",
            "objective": "Understand DNS resolution, HTTP/HTTPS, email protocols, and how routing algorithms (RIP, OSPF, BGP) work.",
            "exam_angle": "🎯 GATE Tip: Distance Vector vs Link State routing (Bellman-Ford vs Dijkstra) is a classic protocol design question.",
            "start_sec": 900,
            "end_sec": None,
            "checkpoints": [
                {
                    "id": "cn-cp3-1", "trigger_pct": 30,
                    "question": "In DNS resolution, which server is queried first when a browser needs to resolve a domain name?",
                    "options": ["The local resolver / ISP's recursive resolver", "The root name server directly", "The authoritative name server", "The TLD name server"],
                    "correct_index": 0,
                    "explanation": "The OS first queries the local DNS resolver (often the ISP). It then does recursive lookup through root → TLD → authoritative."
                },
                {
                    "id": "cn-cp3-2", "trigger_pct": 65,
                    "question": "OSPF uses which algorithm internally to compute shortest paths?",
                    "options": ["Dijkstra's algorithm (Link State)", "Bellman-Ford (Distance Vector)", "Floyd-Warshall", "Kruskal's algorithm"],
                    "correct_index": 0,
                    "explanation": "OSPF is a Link State protocol. Each router builds a complete topology map and runs Dijkstra to compute shortest paths."
                },
                {
                    "id": "cn-cp3-3", "trigger_pct": 85,
                    "question": "What security feature does HTTPS add over HTTP?",
                    "options": ["TLS/SSL encryption and server certificate authentication", "Faster packet routing", "Compression of HTML content", "Stateful session tracking"],
                    "correct_index": 0,
                    "explanation": "HTTPS wraps HTTP in TLS — providing encryption (confidentiality), integrity, and server authentication via certificates."
                }
            ]
        }
    ]
}
