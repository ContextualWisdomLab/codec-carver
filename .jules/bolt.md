## 2024-05-20 - [ transcript_search 성능 개선 ]
**Learning:** Python에서 교집합을 구하기 위해 셋끼리 `&` 연산자를 반복 사용하면, 중간 셋(set) 객체들이 매번 생성되면서 메모리와 성능 오버헤드가 발생한다. 또한, tight inner loop에서 sum과 함께 generator comprehension을 사용하는 것은 성능 저하의 원인이 될 수 있다.
**Action:** `set`의 `.intersection_update()`를 사용하여 메모리 할당 없이 인플레이스로 교집합 연산을 수행하고, 잦은 반복문 내에서는 generator 표현식 대신 단순 for 루프에 값을 누적합하여 처리하도록 한다.
