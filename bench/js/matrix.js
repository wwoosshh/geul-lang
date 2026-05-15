const N = 200;
const A = new Float64Array(N * N);
const B = new Float64Array(N * N);
const C = new Float64Array(N * N);

for (let i = 0; i < N * N; i++) {
    A[i] = i % 100;
    B[i] = (i * 7) % 100;
}

const start = process.hrtime.bigint();

for (let i = 0; i < N; i++) {
    for (let k = 0; k < N; k++) {
        const a_ik = A[i * N + k];
        for (let j = 0; j < N; j++) {
            C[i * N + j] += a_ik * B[k * N + j];
        }
    }
}

const ms = Number(process.hrtime.bigint() - start) / 1e6;

console.log(`C[0][0]=${C[0].toFixed(0)} C[${N-1}][${N-1}]=${C[(N-1) * N + (N-1)].toFixed(0)}`);
console.log(`RESULT:${ms.toFixed(3)}`);
