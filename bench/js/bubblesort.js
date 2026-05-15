// Linear congruential rand matching C stdlib (deterministic seed 42)
// Using simple LCG since JS Math.random isn't seedable
function mulberry32(seed) {
    return function() {
        seed |= 0; seed = seed + 0x6D2B79F5 | 0;
        let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
        t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
        return (t ^ t >>> 14) >>> 0;
    }
}

const n = 30000;
const rand = mulberry32(42);
const arr = new Int32Array(n);
for (let i = 0; i < n; i++) arr[i] = rand() & 0x7FFFFFFF;

const start = process.hrtime.bigint();
for (let i = 0; i < n - 1; i++) {
    for (let j = 0; j < n - i - 1; j++) {
        if (arr[j] > arr[j + 1]) {
            const t = arr[j];
            arr[j] = arr[j + 1];
            arr[j + 1] = t;
        }
    }
}
const ms = Number(process.hrtime.bigint() - start) / 1e6;

console.log(`sorted[0]=${arr[0]} sorted[${n-1}]=${arr[n-1]}`);
console.log(`RESULT:${ms.toFixed(3)}`);
