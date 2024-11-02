import copy

from loguru import logger

from magic_pdf.libs.Constants import LINES_DELETED, CROSS_PAGE
from magic_pdf.libs.ocr_content_type import BlockType, ContentType

LINE_STOP_FLAG = ('.', '!', '?', '。', '！', '？', ')', '）', '"', '”', ':', '：', ';', '；')
LIST_END_FLAG = ('.', '。', ';', '；')


class ListLineTag:
    IS_LIST_START_LINE = "is_list_start_line"
    IS_LIST_END_LINE = "is_list_end_line"


def __process_blocks(blocks):
    # 对所有block预处理
    # 1.通过title和interline_equation将block分组
    # 2.bbox边界根据line信息重置

    result = []
    current_group = []

    for i in range(len(blocks)):
        current_block = blocks[i]

        # 如果当前块是 text 类型
        if current_block['type'] == 'text':
            current_block["bbox_fs"] = copy.deepcopy(current_block["bbox"])
            if 'lines' in current_block and len(current_block["lines"]) > 0:
                current_block['bbox_fs'] = [min([line['bbox'][0] for line in current_block['lines']]),
                                            min([line['bbox'][1] for line in current_block['lines']]),
                                            max([line['bbox'][2] for line in current_block['lines']]),
                                            max([line['bbox'][3] for line in current_block['lines']])]
            current_group.append(current_block)

        # 检查下一个块是否存在
        if i + 1 < len(blocks):
            next_block = blocks[i + 1]
            # 如果下一个块不是 text 类型且是 title 或 interline_equation 类型
            if next_block['type'] in ['title', 'interline_equation']:
                result.append(current_group)
                current_group = []

    # 处理最后一个 group
    if current_group:
        result.append(current_group)

    return result


def __is_list_or_index_block(block):
    # 一个block如果是list block 应该同时满足以下特征
    # 1.block内有多个line 2.block 内有多个line左侧顶格写 3.block内有多个line 右侧不顶格（狗牙状）
    # 1.block内有多个line 2.block 内有多个line左侧顶格写 3.多个line以endflag结尾
    # 1.block内有多个line 2.block 内有多个line左侧顶格写 3.block内有多个line 左侧不顶格

    # index block 是一种特殊的list block
    # 一个block如果是index block 应该同时满足以下特征
    # 1.block内有多个line 2.block 内有多个line两侧均顶格写 3.line的开头或者结尾均为数字
    if len(block['lines']) >= 2:
        first_line = block['lines'][0]
        line_height = first_line['bbox'][3] - first_line['bbox'][1]
        block_weight = block['bbox_fs'][2] - block['bbox_fs'][0]

        left_close_num = 0
        left_not_close_num = 0
        right_not_close_num = 0
        right_close_num = 0
        lines_text_list = []

        multiple_para_flag = False
        last_line = block['lines'][-1]
        # 如果首行左边不顶格而右边顶格,末行左边顶格而右边不顶格 （第一行可能可以右边不顶格）
        if (first_line['bbox'][0] - block['bbox_fs'][0] > line_height / 2 and
                # block['bbox_fs'][2] - first_line['bbox'][2] < line_height and
                abs(last_line['bbox'][0] - block['bbox_fs'][0]) < line_height / 2 and
                block['bbox_fs'][2] - last_line['bbox'][2] > line_height
        ):
            multiple_para_flag = True

        for line in block['lines']:

            line_text = ""

            for span in line['spans']:
                span_type = span['type']
                if span_type == ContentType.Text:
                    line_text += span['content'].strip()

            lines_text_list.append(line_text)

            # 计算line左侧顶格数量是否大于2，是否顶格用abs(block['bbox_fs'][0] - line['bbox'][0]) < line_height/2 来判断
            if abs(block['bbox_fs'][0] - line['bbox'][0]) < line_height / 2:
                left_close_num += 1
            elif line['bbox'][0] - block['bbox_fs'][0] > line_height:
                # logger.info(f"{line_text}, {block['bbox_fs']}, {line['bbox']}")
                left_not_close_num += 1

            # 计算右侧是否顶格
            if abs(block['bbox_fs'][2] - line['bbox'][2]) < line_height:
                right_close_num += 1
            else:
                # 右侧不顶格情况下是否有一段距离，拍脑袋用0.3block宽度做阈值
                closed_area = 0.26 * block_weight
                # closed_area = 5 * line_height
                if block['bbox_fs'][2] - line['bbox'][2] > closed_area:
                    right_not_close_num += 1

        # 判断lines_text_list中的元素是否有超过80%都以LIST_END_FLAG结尾
        line_end_flag = False
        # 判断lines_text_list中的元素是否有超过80%都以数字开头或都以数字结尾
        line_num_flag = False
        num_start_count = 0
        num_end_count = 0
        flag_end_count = 0
        if len(lines_text_list) > 0:
            for line_text in lines_text_list:
                if len(line_text) > 0:
                    if line_text[-1] in LIST_END_FLAG:
                        flag_end_count += 1
                    if line_text[0].isdigit():
                        num_start_count += 1
                    if line_text[-1].isdigit():
                        num_end_count += 1

            if flag_end_count / len(lines_text_list) >= 0.8:
                line_end_flag = True

            if num_start_count / len(lines_text_list) >= 0.8 or num_end_count / len(lines_text_list) >= 0.8:
                line_num_flag = True

        # 有的目录右侧不贴边, 目前认为左边或者右边有一边全贴边，且符合数字规则极为index
        if ((left_close_num/len(block['lines']) >= 0.8 or right_close_num/len(block['lines']) >= 0.8)
                and line_num_flag
        ):
            for line in block['lines']:
                line[ListLineTag.IS_LIST_START_LINE] = True
            return BlockType.Index

        # @TODO 全部line都居中的特殊list识别，每行都需要换行，特征是多行，且大多数行都前后not_close,每line中点x坐标接近

        elif left_close_num >= 2 and (
                right_not_close_num >= 2 or line_end_flag or left_not_close_num >= 2) and not multiple_para_flag:
            # 处理一种特殊的没有缩进的list，所有行都贴左边，通过右边的空隙判断是否是item尾
            if left_close_num / len(block['lines']) > 0.8:
                # 这种是每个item只有一行，且左边都贴边的短item list
                if flag_end_count == 0 and right_close_num / len(block['lines']) < 0.5:
                    for line in block['lines']:
                        if abs(block['bbox_fs'][0] - line['bbox'][0]) < line_height / 2:
                            line[ListLineTag.IS_LIST_START_LINE] = True
                # 这种是大部分line item 都有结束标识符的情况，按结束标识符区分不同item
                elif line_end_flag:
                    for i, line in enumerate(block['lines']):
                        if lines_text_list[i][-1] in LIST_END_FLAG:
                            line[ListLineTag.IS_LIST_END_LINE] = True
                            if i + 1 < len(block['lines']):
                                block['lines'][i+1][ListLineTag.IS_LIST_START_LINE] = True
                # line item基本没有结束标识符，而且也没有缩进，按右侧空隙判断哪些是item end
                else:
                    line_start_flag = False
                    for i, line in enumerate(block['lines']):
                        if line_start_flag:
                            line[ListLineTag.IS_LIST_START_LINE] = True
                            line_start_flag = False
                        # elif abs(block['bbox_fs'][2] - line['bbox'][2]) > line_height:
                        if abs(block['bbox_fs'][2] - line['bbox'][2]) > 0.1 * block_weight:
                            line[ListLineTag.IS_LIST_END_LINE] = True
                            line_start_flag = True
            # 一种有缩进的特殊有序list,start line 左侧不贴边且以数字开头，end line 以 IS_LIST_END_LINE 结尾且数量和start line 一致
            elif num_start_count >= 2 and num_start_count == flag_end_count:  # 简单一点先不考虑左侧不贴边的情况
                for i, line in enumerate(block['lines']):
                    if lines_text_list[i][0].isdigit():
                        line[ListLineTag.IS_LIST_START_LINE] = True
                    if lines_text_list[i][-1] in LIST_END_FLAG:
                        line[ListLineTag.IS_LIST_END_LINE] = True
            else:
                # 正常有缩进的list处理
                for line in block['lines']:
                    if abs(block['bbox_fs'][0] - line['bbox'][0]) < line_height / 2:
                        line[ListLineTag.IS_LIST_START_LINE] = True
                    if abs(block['bbox_fs'][2] - line['bbox'][2]) > line_height:
                        line[ListLineTag.IS_LIST_END_LINE] = True

            return BlockType.List
        else:
            return BlockType.Text
    else:
        return BlockType.Text


def __merge_2_text_blocks(block1, block2):
    if len(block1['lines']) > 0:
        first_line = block1['lines'][0]
        line_height = first_line['bbox'][3] - first_line['bbox'][1]
        block1_weight = block1['bbox'][2] - block1['bbox'][0]
        block2_weight = block2['bbox'][2] - block2['bbox'][0]
        min_block_weight = min(block1_weight, block2_weight)
        if abs(block1['bbox_fs'][0] - first_line['bbox'][0]) < line_height / 2:
            last_line = block2['lines'][-1]
            if len(last_line['spans']) > 0:
                last_span = last_line['spans'][-1]
                line_height = last_line['bbox'][3] - last_line['bbox'][1]
                if (abs(block2['bbox_fs'][2] - last_line['bbox'][2]) < line_height and
                        not last_span['content'].endswith(LINE_STOP_FLAG) and
                        # 两个block宽度差距超过2倍也不合并
                        abs(block1_weight - block2_weight) < min_block_weight
                ):
                    if block1['page_num'] != block2['page_num']:
                        for line in block1['lines']:
                            for span in line['spans']:
                                span[CROSS_PAGE] = True
                    block2['lines'].extend(block1['lines'])
                    block1['lines'] = []
                    block1[LINES_DELETED] = True

    return block1, block2


def __merge_2_list_blocks(block1, block2):
    if block1['page_num'] != block2['page_num']:
        for line in block1['lines']:
            for span in line['spans']:
                span[CROSS_PAGE] = True
    block2['lines'].extend(block1['lines'])
    block1['lines'] = []
    block1[LINES_DELETED] = True

    return block1, block2


def __is_list_group(text_blocks_group):
    # list group的特征是一个group内的所有block都满足以下条件
    # 1.每个block都不超过3行 2. 每个block 的左边界都比较接近(逻辑简单点先不加这个规则)
    for block in text_blocks_group:
        if len(block['lines']) > 3:
            return False
    return True


def __para_merge_page(blocks):
    page_text_blocks_groups = __process_blocks(blocks)
    for text_blocks_group in page_text_blocks_groups:

        if len(text_blocks_group) > 0:
            # 需要先在合并前对所有block判断是否为list or index block
            for block in text_blocks_group:
                block_type = __is_list_or_index_block(block)
                block['type'] = block_type
                # logger.info(f"{block['type']}:{block}")

        if len(text_blocks_group) > 1:

            # 在合并前判断这个group 是否是一个 list group
            is_list_group = __is_list_group(text_blocks_group)

            # 倒序遍历
            for i in range(len(text_blocks_group) - 1, -1, -1):
                current_block = text_blocks_group[i]

                # 检查是否有前一个块
                if i - 1 >= 0:
                    prev_block = text_blocks_group[i - 1]

                    if current_block['type'] == 'text' and prev_block['type'] == 'text' and not is_list_group:
                        __merge_2_text_blocks(current_block, prev_block)
                    elif (
                            (current_block['type'] == BlockType.List and prev_block['type'] == BlockType.List) or
                            (current_block['type'] == BlockType.Index and prev_block['type'] == BlockType.Index)
                    ):
                        __merge_2_list_blocks(current_block, prev_block)

        else:
            continue


def para_split(pdf_info_dict, debug_mode=False):
    all_blocks = []
    for page_num, page in pdf_info_dict.items():
        blocks = copy.deepcopy(page['preproc_blocks'])
        for block in blocks:
            block['page_num'] = page_num
        all_blocks.extend(blocks)

    __para_merge_page(all_blocks)
    for page_num, page in pdf_info_dict.items():
        page['para_blocks'] = []
        for block in all_blocks:
            if block['page_num'] == page_num:
                page['para_blocks'].append(block)


if __name__ == '__main__':
    input_blocks = []
    # 调用函数
    groups = __process_blocks(input_blocks)
    for group_index, group in enumerate(groups):
        print(f"Group {group_index}: {group}")
