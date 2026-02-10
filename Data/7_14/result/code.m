% Excel 파일 읽기
filename = 'pressure1.xlsx'; % 여기에 실제 엑셀 파일 이름을 입력하세요.
data = readtable(filename);

% A열과 B열 데이터 추출
x_data = data{:, 1}; % 첫 번째 열 (A열) 데이터를 x축으로 지정
y_data = data{:, 2}; % 두 번째 열 (B열) 데이터를 y축으로 지정

% 그래프 그리기
plot(x_data, y_data, 'LineWidth', 1.5);

% 그래프 제목 및 축 레이블 추가 (선택 사항)
title('연소실험 압력 데이터 분석');
xlabel('시간 [s]');
ylabel('압력 [bar]');
xlim([0 4]);
ylim([-10 50]);
grid on; % 그리드 표시