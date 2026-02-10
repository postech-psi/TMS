% --- 1. 그래프 초기화 및 첫 번째 파일 그리기 ---
figure; % 새로운 그래프 창을 엽니다.

% 첫 번째 엑셀 파일 읽고 그래프 그리기
data1 = readtable('test1.xlsx');
plot(data1{:, 1}, data1{:, 2});

% --- 2. 그래프 중첩을 위해 hold on 실행 ---
hold on; 

% --- 3. 나머지 파일들 그리기 ---
% 두 번째 엑셀 파일
data2 = readtable('test2.xlsx');
plot(data2{:, 1}, data2{:, 2});

% 세 번째 엑셀 파일
data3 = readtable('test3.xlsx');
plot(data3{:, 1}, data3{:, 2});

% --- 4. 그래프 중첩 끝내기 ---
hold off; 

% --- 5. 그래프 꾸미기 ---
grid on; % 그리드 추가
title('여러 엑셀 파일 데이터 비교'); % 그래프 제목
xlabel('A열 (X축)'); % X축 레이블
ylabel('B열 (Y축)'); % Y축 레이블
legend('데이터 1', '데이터 2', '데이터 3'); % 범례 추가 (순서 중요)