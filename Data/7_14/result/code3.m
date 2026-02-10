%% 1. 초기화 및 파일 목록 정의
clear;       % 작업 공간 변수 초기화
clc;         % 명령 창 지우기
close all;   % 열려있는 모든 그림 창 닫기

% --- 사용자가 수정할 부분 ---
file_list = {'test1.xlsx', 'test2.xlsx', 'test3.xlsx'}; 
thrust_threshold = 10; % 추력으로 인식할 임계값 (단위: N)
% --------------------------

%% 2. 그래프 창 준비 및 반복문 시작
figure;      % 결과물을 그릴 새로운 그래프 창 생성
hold on;     % 여러 그래프를 겹쳐 그리기 위해 hold on 상태로 전환
colors = [0 0.4470 0.7410;    % 파란색 (MATLAB 기본)
          0.8500 0.3250 0.0980;    % 주황색
          0.9290 0.6940 0.1250];   % 노란색

% for 반복문을 사용하여 각 파일을 순서대로 처리
for i = 1:length(file_list)
    
    fprintf('------------------------------------------\n');
    fprintf('■ 처리 중인 파일: %s\n', file_list{i}); % 진행 상황 표시
    
    % --- A. 데이터 불러오기 및 슬라이싱 ---
    try
        current_data = readtable(file_list{i});
    catch
        warning('파일을 찾을 수 없습니다: %s. 이 파일을 건너뜁니다.', file_list{i});
        continue;
    end
    
    x_data = current_data{:, 1};       % A열 -> x축 (시간)
    y_noisy_data = current_data{:, 2}; % B열 -> y축 (추력)

    % --- B. 로우패스 필터 설계 및 적용 ---
    Fs = 1 / mean(diff(x_data)); 
    filter_order = 20;
    cutoff_freq = 10;
    
    lp_filter = designfilt('lowpassfir', 'FilterOrder', filter_order, ...
                           'CutoffFrequency', cutoff_freq, 'SampleRate', Fs);
                           
    y_filtered_data = filtfilt(lp_filter, y_noisy_data);

    % --- C. 연소 성능 지표 계산 ---
    % y값이 임계값을 넘어가는 모든 지점의 인덱스를 찾음
    above_threshold_indices = find(y_filtered_data >= thrust_threshold);
    
    if isempty(above_threshold_indices)
        fprintf('  >> 추력이 임계값(%.1f N)을 넘지 않아 계산을 건너뜁니다.\n', thrust_threshold);
        plot_name = sprintf('%s (데이터 없음)', file_list{i});
    else
        % 연소 시작 및 종료 시간(x1, x2) 찾기
        start_index = above_threshold_indices(1);
        % 시작 지점 이후로 다시 임계값 아래로 내려오는 첫 지점을 찾음
        end_index_relative = find(y_filtered_data(start_index:end) < thrust_threshold, 1);
        if isempty(end_index_relative)
            end_index = length(y_filtered_data); % 끝까지 안내려오면 마지막을 종료점으로 간주
        else
            end_index = start_index + end_index_relative - 1;
        end

        x1 = x_data(start_index); % 연소 시작 시간
        x2 = x_data(end_index);   % 연소 종료 시간
        
        % 연소 구간의 데이터만 추출
        combustion_x = x_data(start_index:end_index);
        combustion_y = y_filtered_data(start_index:end_index);

        % 1. 연소 시간 계산
        combustion_time = x2 - x1;

        % 2. 충격량 계산 (그래프 적분)
        total_impulse = trapz(combustion_x, combustion_y);

        % 3. 최대 추력 계산
        max_thrust = max(combustion_y);
        
        % 4. 평균 추력 계산
        avg_thrust = total_impulse / combustion_time;

        % 계산 결과 출력
        fprintf('  - 최대 추력  : %.2f N\n', max_thrust);
        fprintf('  - 연소 시간  : %.3f s\n', combustion_time);
        fprintf('  - 총 충격량  : %.2f N·s\n', total_impulse);
        fprintf('  - 평균 추력  : %.2f N\n', avg_thrust);
        
        plot_name = sprintf('%s (평균: %.1f N)', file_list{i}, avg_thrust);
    end
    
    % --- D. 현재 파일의 필터링된 결과 플롯 ---
    plot(x_data, y_filtered_data, 'Color', colors(i, :), 'LineWidth', 1.5, 'DisplayName', plot_name);

end % 반복문 끝

%% 4. 최종 그래프 꾸미기
hold off; 
grid on;
title('연소실험 추력 데이터 분석');
xlabel('시간 [s]');
ylabel('추력 [N]');
xlim([0 4]);
ylim([-100 600]);
legend('Location', 'northeast'); % 범례 위치를 우측 상단으로 지정
fprintf('------------------------------------------\n');