from utils import (
    log2, M31, M31SQ, HALF, to_extension_field, mul_ext, modinv,
    np, array, zeros, tobytes, arange, reverse_bit_order,
    merkelize_top_dimension, get_challenges, rbo_index_to_original
)
from precomputes import folded_rbos, invx, invy
from fast_fft import fft
from merkle import merkelize, hash, get_branch, verify_branch

BASE_CASE_SIZE = 128
FOLDS_PER_ROUND = 3
FOLD_SIZE_RATIO = 2**FOLDS_PER_ROUND
NUM_CHALLENGES = 80

def fold(values, coeff, first_round):
    for i in range(FOLDS_PER_ROUND):
        full_len, half_len = values.shape[-2], values.shape[-2]//2
        left, right = values[::2], values[1::2]
        f0 = ((left + right) * HALF) % M31
        if i == 0 and first_round:
            twiddle = \
                invy[full_len: full_len + half_len][folded_rbos[half_len:full_len]]
        else:
            twiddle = \
                invx[full_len*2: full_len*2 + half_len][folded_rbos[half_len:full_len]]
        twiddle_box = np.zeros_like(left)
        twiddle_box[:] = twiddle.reshape((half_len,) + (1,) * (left.ndim-1))
        f1 = ((((left + M31 - right) * HALF) % M31) * twiddle_box) % M31
        values = (f0 + mul_ext(f1, coeff)) % M31
    return values

def fold_with_positions(values, domain_size, positions, coeff, first_round):
    positions = positions[::2]
    for i in range(FOLDS_PER_ROUND):
        left, right = values[::2], values[1::2]
        f0 = ((left + right) * HALF) % M31
        if i == 0 and first_round:
            unrbo_positions = rbo_index_to_original(domain_size, positions)
            twiddle = invy[domain_size + unrbo_positions]
        else:
            unrbo_positions = rbo_index_to_original(
                domain_size * 2,
                (positions << 1) >> i
            )
            twiddle = invx[domain_size * 2 + unrbo_positions]
        twiddle_box = np.zeros_like(left)
        twiddle_box[:] = twiddle.reshape((left.shape[0],) + (1,)*(left.ndim-1))
        f1 = ((((left + M31 - right) * HALF) % M31) * twiddle_box) % M31
        values = (f0 + mul_ext(f1, coeff)) % M31
        positions = positions[::2]
        domain_size //= 2
    return values

def prove_low_degree(evaluations):
    assert len(evaluations.shape) == 2 and evaluations.shape[-1] == 4
    # Commit Merkle root
    values = evaluations[folded_rbos[len(evaluations):len(evaluations)*2]]
    leaves = []
    trees = []
    roots = []
    # Prove descent
    rounds = log2(len(evaluations) // BASE_CASE_SIZE) // FOLDS_PER_ROUND
    print("Generating FRI proof")
    for i in range(rounds):
        leaves.append(values)
        trees.append(merkelize_top_dimension(values.reshape(
            (len(values) // FOLD_SIZE_RATIO, FOLD_SIZE_RATIO)
            + values.shape[1:]
        )))
        roots.append(trees[-1][1])
        print('Root: 0x{}'.format(roots[-1].hex()))
        print("Descent round {}: {} values".format(i+1, len(values)))
        fold_factor = get_challenges(b''.join(roots), M31, 4)
        print("Fold factor: {}".format(fold_factor))
        values = fold(values, fold_factor, i==0)
    entropy = b''.join(roots) + tobytes(values)
    challenges = get_challenges(
        entropy, len(evaluations) >> FOLDS_PER_ROUND, NUM_CHALLENGES
    )
    round_challenges = (
        challenges.reshape((1,)+challenges.shape)
        >> arange(0, rounds * FOLDS_PER_ROUND, FOLDS_PER_ROUND)
        .reshape((rounds,) + (1,) * challenges.ndim)
    )

    branches = [
        [get_branch(tree, c) for c in r_challenges]
        for i, (r_challenges, tree) in enumerate(zip(round_challenges, trees))
    ]
    round_challenges_xfold = (
        round_challenges.reshape(round_challenges.shape + (1,)) * 8
        + arange(FOLD_SIZE_RATIO).reshape(1, 1, FOLD_SIZE_RATIO)
    )

    leaf_values = [
        leaves[i][round_challenges_xfold[i]]
        for i in range(rounds)
    ]
    return {
        "roots": roots,
        "branches": branches,
        "leaf_values": leaf_values,
        "final_values": values
    }

def verify_low_degree(proof):
    roots = proof["roots"]
    branches = proof["branches"]
    leaf_values = proof["leaf_values"]
    final_values = proof["final_values"]
    len_evaluations = final_values.shape[0] << (FOLDS_PER_ROUND * len(roots))
    print("Verifying FRI proof")
    # Prove descent
    entropy = b''.join(roots) + tobytes(final_values)
    challenges = get_challenges(
        entropy, len_evaluations >> FOLDS_PER_ROUND, NUM_CHALLENGES
    )
    for i in range(len(roots)):
        print("Descent round {}".format(i+1))
        fold_factor = get_challenges(b''.join(roots[:i+1]), M31, 4)
        print("Fold factor: {}".format(fold_factor))
        evaluation_size = len_evaluations >> (i * FOLDS_PER_ROUND)
        positions = (
            challenges.reshape((NUM_CHALLENGES, 1)) * FOLD_SIZE_RATIO
            + arange(FOLD_SIZE_RATIO)
        ).reshape((NUM_CHALLENGES * FOLD_SIZE_RATIO))
        folded_values = fold_with_positions(
            leaf_values[i].reshape((-1,4)),
            evaluation_size,
            positions,
            fold_factor,
            i==0
        )
        if i < len(roots) - 1:
            expected_values = (
                leaf_values[i+1][
                    arange(NUM_CHALLENGES),
                    challenges % FOLD_SIZE_RATIO
                ]
            )
        else:
            expected_values = final_values[challenges]
        assert np.array_equal(folded_values, expected_values)
        for j, c in enumerate(np.copy(challenges)):
            assert verify_branch(
                roots[i], c, tobytes(leaf_values[i][j]), branches[i][j]
            )
        challenges >>= FOLDS_PER_ROUND
    o = np.zeros_like(final_values)
    N = final_values.shape[0]
    o[rbo_index_to_original(N, arange(N))] = final_values
    coeffs = fft(o, is_top_level=False)
    assert not np.any(coeffs[N//2:])
    return True
