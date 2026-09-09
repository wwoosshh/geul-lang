int shipping(int amount) {
    if (amount < 0) return -1;
    if (amount >= 50000) return 0;
    return 3000;
}
