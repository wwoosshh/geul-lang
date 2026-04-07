# 글 컴파일러 - 부트스트랩 빌드 시스템
CC = gcc
CFLAGS = -Wall -Wextra -std=c11 -Iinclude -g
LDFLAGS =

SRC_DIR = src
INC_DIR = include
BUILD_DIR = build

# 소스 파일
SOURCES = $(SRC_DIR)/유니코드.c \
          $(SRC_DIR)/토큰.c \
          $(SRC_DIR)/형태소분석기.c \
          $(SRC_DIR)/구문트리.c \
          $(SRC_DIR)/구문분석기.c \
          $(SRC_DIR)/주.c

# 오브젝트 파일
OBJECTS = $(patsubst $(SRC_DIR)/%.c,$(BUILD_DIR)/%.o,$(SOURCES))

# 실행 파일
TARGET = $(BUILD_DIR)/글cc

.PHONY: all clean test

all: $(TARGET)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(TARGET): $(OBJECTS)
	$(CC) $(OBJECTS) $(LDFLAGS) -o $@
	@echo ""
	@echo "=== 빌드 완료: $(TARGET) ==="
	@echo ""

clean:
	rm -rf $(BUILD_DIR)

# 테스트 실행
test: $(TARGET)
	@echo "=== 렉서 테스트: 인사.글 ==="
	$(TARGET) -토큰 ../예제/인사.글
	@echo ""
	@echo "=== 파서 테스트: 인사.글 ==="
	$(TARGET) -구문 ../예제/인사.글
	@echo ""
	@echo "=== 렉서 테스트: 변수.글 ==="
	$(TARGET) -토큰 ../예제/변수.글
	@echo ""
	@echo "=== 파서 테스트: 변수.글 ==="
	$(TARGET) -구문 ../예제/변수.글
