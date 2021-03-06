import numpy as np
import random
import time
import distance

class LSHBuilder:

    methods = ["opt",
        "uniform",
        "weighted_uniform",
        "approx_degree",
        "rank"]

    @staticmethod
    def build(d, r, k, L, lsh_params, validate=False):
        if lsh_params['type'] == 'e2lsh':
            return E2LSH(k, L, lsh_params['w'], d, r, validate)
        if lsh_params['type'] == 'onebitminhash':
            return OneBitMinHash(k, L, r, validate)

    @staticmethod
    def invoke(lsh, method, queries, runs):
        assert method in LSHBuilder.methods
        if method == "opt":
            res = lsh.opt(queries, runs)
        if method == "uniform":
            res = lsh.uniform_query(queries, runs)
        if method == "weighted_uniform":
            res = lsh.weighted_uniform_query(queries, runs)
        if method == "approx_degree":
            res = lsh.approx_degree_query(queries, runs)
        if method == "rank":
            res = lsh.rank_query_simulate(queries, runs)
        return res


class LSH:

    def preprocess(self, X):
        self.X = X
        n = len(X)
        hvs = self._hash(X)
        self.tables = [{} for _ in range(self.L)]
        for i in range(n):
            for j in range(self.L):
                h = self._get_hash_value(hvs[i], j)
                self.tables[j].setdefault(h, set()).add(i)

    def preprocess_query(self, Y):
        """Collect buckets, bucket sizes, and prefix_sums
        to quickly answer queries."""
        query_buckets = [[] for _ in range(len(Y))]
        query_size = [0 for _ in range(len(Y))]
        bucket_sizes = [0 for _ in range(len(Y))]
        prefix_sums = [[0 for _ in range(self.L)] for _ in range(len(Y))]
        query_results = [set() for _ in range(len(Y))]

        hvs = self._hash(Y)
        for j, q in enumerate(hvs):
            buckets = [(i, self._get_hash_value(q, i)) for i in range(self.L)]
            query_buckets[j] = buckets
            s = 0
            elements = set()
            for i, (table, bucket) in enumerate(buckets):
                s += len(self.tables[table].get(bucket, []))
                elements |= self.tables[table].get(bucket, set())
                prefix_sums[j][i] = s
            elements = set(x for x in elements
                if self.is_candidate_valid(Y[j], self.X[x]))
            bucket_sizes[j] = s
            query_size[j] = len(elements)
            query_results[j] = elements

        return (query_buckets, query_size, query_results,
            bucket_sizes, prefix_sums)


    def get_query_size(self, Y):
        _, query_size, _, _, _ = self.preprocess_query(Y)
        return query_size

    def uniform_query(self, Y, runs=100):
        query_bucket, sizes, query_results, _, _ = self.preprocess_query(Y)
        results = {i: [] for i in range(len(Y))}
        for j in range(len(Y)):
            for _ in range(sizes[j] * runs):
                if len(query_results[j]) == 0:
                    results[j].append(-1)
                    continue
                while True:
                    table, bucket = query_bucket[j][random.randrange(0, self.L)]
                    elements = list(self.tables[table].get(bucket, [-1]))
                    p = random.choice(elements)
                    if p != -1 and self.is_candidate_valid(Y[j], self.X[p]):
                        results[j].append(p)
                        break
        return results

    def weighted_uniform_query(self, Y, runs=100):
        from bisect import bisect_right
        query_buckets, query_size, elements, bucket_sizes, prefix_sums = self.preprocess_query(Y)
        results = {i: [] for i in range(len(Y))}

        for j in range(len(Y)):
            for _ in range(query_size[j] * runs):
                if len(elements[j]) == 0:
                    results[j].append(-1)
                    continue
                while True:
                    i = random.randrange(bucket_sizes[j])
                    pos = bisect_right(prefix_sums[j], i)
                    table, bucket = query_buckets[j][pos]
                    p = random.choice(list(self.tables[table][bucket]))
                    if self.is_candidate_valid(Y[j], self.X[p]):
                        results[j].append(p)
                        break
        return results

    def opt(self, Y, runs=100, runs_per_collision=True):
        _, query_size, query_results, _, _ = self.preprocess_query(Y)
        results = {i: [] for i in range(len(Y))}

        for j in range(len(Y)):
            elements = list(query_results[j])
            iterations = query_size[j] * runs
            if not runs_per_collision:
                iterations = runs
            for _ in range(iterations):
                if query_size[j] == 0:
                    results[j].append(-1)
                    continue
                results[j].append(random.choice(elements))
        return results

    def approx_degree_query(self, Y, runs=100):
        from bisect import bisect_right
        query_buckets, query_size, _, bucket_sizes, prefix_sums = self.preprocess_query(Y)
        results = {i: [] for i in range(len(Y))}

        for j in range(len(Y)):
            cache = {}

            for _ in range(query_size[j] * runs):
                if bucket_sizes[j] == 0:
                    results[j].append(-1)
                    continue
                while True:
                    i = random.randrange(bucket_sizes[j])
                    pos = bisect_right(prefix_sums[j], i)
                    table, bucket = query_buckets[j][pos]
                    p = random.choice(list(self.tables[table][bucket]))
                    # discard not within distance threshold
                    if not self.is_candidate_valid(Y[j], self.X[p]):
                        continue
                    #if p not in cache:
                    #    cache[p] = int(np.median([self.approx_degree(query_buckets[j], p) for _ in range(30)]))
                    D = self.approx_degree(query_buckets[j], p) #cache[p]
                    if random.randint(1, D) == D: # output with probability 1/D
                        results[j].append(p)
                        break
        return results

    def rank_query_simulate(self, Y, runs=100):
        import heapq
        n = len(self.X)
        m = len(Y)
        # ranks[i] is point with rank i
        # point_rank[j] is the rank of point j
        ranks = list(range(n))
        point_rank = [0 for _ in range(n)]
        random.shuffle(ranks)

        for rank, point in enumerate(ranks):
            point_rank[point] = rank

        results = {i: [] for i in range(m)}

        query_buckets, query_size, query_results, _, _ = self.preprocess_query(Y)

        for j in range(m):
            elements = list((point_rank[point], point) for point in query_results[j])
            heapq.heapify(elements)
            for _ in range(query_size[j] * runs):
                while True:
                    rank, point = heapq.heappop(elements)
                    while rank != point_rank[point]:
                        rank, point = heapq.heappop(elements)
                    if self.is_candidate_valid(Y[j], self.X[point]):
                       break

                results[j].append(point)

                new_rank = random.randrange(rank, n)
                q = ranks[new_rank]
                ranks[rank] = q
                ranks[new_rank] = point
                point_rank[q] = rank
                point_rank[point] = new_rank

                heapq.heappush(elements, (new_rank, point))
                if q in query_results[j]:
                    heapq.heappush(elements, (rank, q))
        return results

    def approx_degree(self, buckets, q):
        num = 0
        L = len(buckets)
        while num < L:
            num += 1
            table, bucket = buckets[random.randrange(0, L)]
            if q in self.tables[table].get(bucket, set()):
                break
        return L // num

    def exact_degree(self, buckets, q):
        cnt = 0
        for table, bucket in buckets:
            if q in self.tables[table].get(bucket, set()):
                cnt += 1
        return cnt

    def is_candidate_valid(self, q, x):
        pass

class MinHash():
    def __init__(self):
        # choose four random 8 bit tables
        self.t1 = [random.randint(0, 2**32 - 1) for _ in range(2**8)]
        self.t2 = [random.randint(0, 2**32 - 1) for _ in range(2**8)]
        self.t3 = [random.randint(0, 2**32 - 1) for _ in range(2**8)]
        self.t4 = [random.randint(0, 2**32 - 1) for _ in range(2**8)]

    def _intern_hash(self, x):
        return self.t1[(x >> 24) & 0xff] ^ self.t2[(x >> 16) & 0xff ] ^\
            self.t3[(x >> 8) & 0xff] ^ self.t4[x & 0xff]

    def _hash(self, X):
        return min([self._intern_hash(x) for x in X])

    def get_element(self, L):
        h = self.hash(L)
        for x in L:
            if self.intern_hash(x) == h:
                return x

class OneBitMinHash(LSH):
    def __init__(self, k, L, r, validate=True, seed=3):
        self.k = k
        self.L = L
        self.r = r
        self.hash_fcts = [[MinHash() for _ in range(k)] for _ in range(L)]
        self.validate = validate

    def _hash(self, X):
        self.hvs = []
        for x in X:
            self.hvs.append([])
            for hash_fct in self.hash_fcts:
                h = 0
                for hf in hash_fct:
                    h += hf._hash(x) % 2
                    h *= 2
                self.hvs[-1].append(h)
        return self.hvs

    def _get_hash_value(self, arr, idx):
        return arr[idx]

    def is_candidate_valid(self, q, x):
        return not self.validate or distance.jaccard(q, x) >= self.r

    def __str__(self):
        return f"OneBitMinHash(k={self.k}, L={self.L})"

    def __repr__(self):
        return f"k_{self.k}_L_{self.L}"


class E2LSH(LSH):
    def __init__(self, k, L, w, d, r, validate=True, seed=3):
        np.random.seed(seed)
        random.seed(seed)
        self.A = np.random.normal(0.0, 1.0, (d, k * L))
        self.b = np.random.uniform(0.0, w, (1, k * L))
        self.w = w
        self.L = L
        self.k = k
        self.r = r
        self.validate = validate

    def _hash(self, X):
        #X = np.transpose(X)
        hvs = np.matmul(X, self.A)
        hvs += self.b
        hvs /= self.w
        return np.floor(hvs).astype(np.int32)

    def _get_hash_value(self, arr, idx):
        return tuple(arr[idx * self.k: (idx + 1) * self.k])

    def is_candidate_valid(self, q, x):
        #print(distance.l2(q, x))
        return not self.validate or distance.l2(q, x) <= self.r

    def __str__(self):
        return f"E2LSH(k={self.k}, L={self.L}, w={self.w})"

    def __repr__(self):
        return f"k_{self.k}_L_{self.L}_w_{self.w}"

def test_minhash():
    n = 10000
    m = 100
    d = 10
    k = 4
    L = 10

    lsh = OneBitMinHash(k, L)
    X = [[random.choice(list(range(100))) for _ in range(d)] for _ in range(n)]
    Y = [[random.choice(list(range(100))) for _ in range(d)] for _ in range(m)]
    lsh.preprocess(X)
    s = time.time()
    lsh.weighted_uniform_query(Y)
    print(time.time() - s)

def test_euclidean():
    d = 10
    n = 10000
    m = 100
    w = 4.0
    k = 2
    L = 3
    lsh = E2LSH(k, L, w, d)
    X = np.random.normal(0.0, 1.0, (d, n))
    lsh.preprocess(X)
    Y = np.random.normal(0.0, 1.0, (d, m))
    s = time.time()
    lsh.weighted_uniform_query(Y)
    print(time.time() - s)

if __name__ == "__main__":
    test_euclidean()
    test_minhash()

