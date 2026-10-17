#include <limits.h>
#include <stdio.h>

int main(void)
{
    int n, m, source, weights[100][100], distances[100], visited[100] = {0};
    if (scanf("%d %d %d", &n, &m, &source) != 3)
        return 1;
    for (int i = 0; i < n; ++i) {
        distances[i] = INT_MAX;
        for (int j = 0; j < n; ++j)
            weights[i][j] = INT_MAX;
    }
    for (int i = 0; i < m; ++i) {
        int a, b, weight;
        if (scanf("%d %d %d", &a, &b, &weight) != 3)
            return 1;
        if (weight < weights[a][b])
            weights[a][b] = weight;
    }
    distances[source] = 0;
    for (int i = 0; i < n; ++i) {
        int closest = -1;
        for (int j = 0; j < n; ++j)
            if (!visited[j] && (closest == -1 || distances[j] < distances[closest]))
                closest = j;
        if (closest == -1 || distances[closest] == INT_MAX)
            break;
        visited[closest] = 1;
        for (int j = 0; j < n; ++j)
            if (weights[closest][j] != INT_MAX &&
                distances[closest] + weights[closest][j] < distances[j])
                distances[j] = distances[closest] + weights[closest][j];
    }
    for (int i = 0; i < n; ++i)
        printf("%s%d", i ? " " : "", distances[i] == INT_MAX ? -1 : distances[i]);
    putchar('\n');
    return 0;
}
