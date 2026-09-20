/* 핫스왑 기계-수준 실행 가능성 탐침 (글이 아니라 C; 이 머신에서 OS/보안 SW 가
 * 협조적 핫스왑을 허용하는지만 본다). kernel32 만 쓴다 — 글의 불변식과 같다.
 *
 * 협조 설계 그대로:
 *   - VirtualAlloc 으로 내 프로세스 안에 메모리를 잡는다 (남의 프로세스 주입 아님)
 *   - 쓸 때는 RW, 실행할 때는 RX. 쓰기+실행을 동시에 주지 않는다 (W^X)
 *   - 함수 프롤로그 덮어쓰기(후킹) 없음 — 포인터로 부른다
 *
 * v1: 함수 본문 mov eax, 111; ret 을 넣고 포인터로 부른다.
 * v2: 같은 자리를 mov eax, 222; ret 로 다시 써서 부른다 (본문 교체).
 * 111, 222 를 둘 다 찍으면 이 머신에서 협조적 핫스왑이 가능하다.
 */
#include <windows.h>
#include <stdio.h>

typedef int (*fn)(void);

/* mov eax, imm32 ; ret  →  B8 <imm32 리틀엔디언> C3 */
static void write_body(unsigned char *p, int imm) {
    p[0] = 0xB8;
    p[1] = (unsigned char)(imm & 0xFF);
    p[2] = (unsigned char)((imm >> 8) & 0xFF);
    p[3] = (unsigned char)((imm >> 16) & 0xFF);
    p[4] = (unsigned char)((imm >> 24) & 0xFF);
    p[5] = 0xC3;
}

int main(void) {
    SIZE_T size = 4096;
    DWORD old;

    unsigned char *mem = (unsigned char *)VirtualAlloc(
        NULL, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!mem) { printf("FAIL VirtualAlloc %lu\n", GetLastError()); return 1; }

    /* v1 코드 배치 (RW 상태에서 쓰기) */
    write_body(mem, 111);

    /* RW → RX 로 좁힌다 (W^X) */
    if (!VirtualProtect(mem, size, PAGE_EXECUTE_READ, &old)) {
        printf("FAIL VirtualProtect->RX %lu\n", GetLastError()); return 1; }
    FlushInstructionCache(GetCurrentProcess(), mem, size);

    int r1 = ((fn)mem)();
    printf("v1 = %d\n", r1);

    /* 본문 교체: RX → RW, 다시 쓰고, RW → RX */
    if (!VirtualProtect(mem, size, PAGE_READWRITE, &old)) {
        printf("FAIL VirtualProtect->RW %lu\n", GetLastError()); return 1; }
    write_body(mem, 222);
    if (!VirtualProtect(mem, size, PAGE_EXECUTE_READ, &old)) {
        printf("FAIL VirtualProtect->RX(2) %lu\n", GetLastError()); return 1; }
    FlushInstructionCache(GetCurrentProcess(), mem, size);

    int r2 = ((fn)mem)();
    printf("v2 = %d\n", r2);

    VirtualFree(mem, 0, MEM_RELEASE);

    if (r1 == 111 && r2 == 222) {
        printf("PASS 협조적 핫스왑 기계-수준 가능 (본문 교체 반영됨)\n");
        return 0;
    }
    printf("FAIL 예상값 불일치\n");
    return 1;
}
