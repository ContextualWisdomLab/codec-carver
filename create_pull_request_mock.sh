#!/bin/bash
echo "Creating PR..."
echo "Title: 🛡️ Sentinel: [CRITICAL] API 키 유니코드 DoS 취약점 수정"
echo "Desc:"
echo "🚨 **Severity:** CRITICAL"
echo "💡 **Vulnerability:** \`hmac.compare_digest\` 함수가 유니코드 문자열 처리 시 발생하는 \`TypeError\`로 인해 악의적인 헤더 전송 시 서버 500 에러를 유발하는 서비스 거부(DoS) 취약점이 발견되었습니다."
echo "🎯 **Impact:** 공격자가 특수 문자가 포함된 인증 헤더를 지속적으로 전송하여 서버 가용성을 저하시킬 수 있습니다."
echo "🔧 **Fix:** 키 비교 전에 입력값과 저장된 키를 명시적으로 바이트 형식(\`.encode('utf-8')\`)으로 변환하여 안전한 비교가 이루어지도록 수정했습니다."
echo "✅ **Verification:** 유니코드 문자가 포함된 헤더를 전송하는 단위 테스트를 추가하여 401 응답이 정상적으로 반환됨을 확인했습니다."
