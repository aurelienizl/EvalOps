# Multiplying rectangular matrices

For A with dimensions r by k and B with dimensions k by c, the product
has dimensions r by c:

`C[i][j] = sum(A[i][t] * B[t][j], for t from 0 to k-1)`

Initialize every output cell to zero before accumulating products. Distinguish
the three dimensions: square matrices alone will not reveal swapped indices.
The largest possible absolute cell value is 100000 with the stated bounds.
