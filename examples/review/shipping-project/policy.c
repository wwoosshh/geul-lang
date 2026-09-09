int free_limit(void);
int standard_fee(void);

int shipping(int amount) {
    if (amount < 0) return -1;
    if (amount >= free_limit()) return 0;
    return standard_fee();
}
