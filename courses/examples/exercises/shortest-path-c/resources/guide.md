# Shortest paths in a directed graph

Weights are nonnegative, so Dijkstra's algorithm is suitable. For at most
100 vertices, scanning an array to choose the next vertex is sufficient.

- Preserve edge direction.
- A zero-weight edge is different from an absent edge.
- Keep the smallest weight when parallel edges connect the same vertices.
- Stop when every remaining unvisited vertex is unreachable.
- Use a suitably large infinity value; print -1 for unreachable vertices.

A longer route in edge count can still have a smaller total weight.
