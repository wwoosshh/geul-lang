function fib(n) {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}

const start = process.hrtime.bigint();
const result = fib(40);
const ms = Number(process.hrtime.bigint() - start) / 1e6;
console.log(`fib(40) = ${result}`);
console.log(`RESULT:${ms.toFixed(3)}`);
