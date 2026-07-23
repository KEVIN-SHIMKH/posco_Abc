"""파이썬 함수와 클래스의 기본 사용 예제입니다."""


def add_numbers(first: float, second: float) -> float:
    """두 수를 더한 값을 반환합니다."""
    return first + second


def is_even(number: int) -> bool:
    """정수가 짝수이면 True를 반환합니다."""
    return number % 2 == 0


class Student:
    """이름과 점수를 관리하는 간단한 학생 클래스입니다."""

    def __init__(self, name: str, score: float) -> None:
        self.name = name
        self.score = score

    def introduce(self) -> str:
        """학생 정보를 사람이 읽기 쉬운 문장으로 반환합니다."""
        return f"안녕하세요. 저는 {self.name}이고, 점수는 {self.score}점입니다."

    def passed(self, passing_score: float = 60) -> bool:
        """기준 점수 이상인지 판정합니다."""
        return self.score >= passing_score


if __name__ == "__main__":
    print(add_numbers(10, 20))
    print(is_even(7))

    student = Student("홍길동", 85)
    print(student.introduce())
    print(student.passed())
