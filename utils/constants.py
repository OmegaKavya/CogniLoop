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
