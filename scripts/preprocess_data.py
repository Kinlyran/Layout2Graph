#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:weishu
# datetime:2022/11/1 10:29 上午
# software: PyCharm
import argparse
import copy
import glob
import json
import math
import re

import requests
import os
import xml.etree.ElementTree as ET
from collections import Counter
import os
import shutil
import json
import unittest
import random
import numpy as np
import time
import cv2
import sys

from PIL.Image import Image
from tqdm import tqdm

from networks.graph_net.graph_net import _get_nearest_pair_knn, _get_nearest_pair_custom, \
    _get_nearest_pair_beta_skeleton

PROJECT_ROOT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT_PATH)


# from base.common_util import get_file_path_list
def get_file_path_list(path, ext=None):
    if not path.startswith('/'):
        path = os.path.join(PROJECT_ROOT_PATH, path)
    # print(path)
    assert os.path.exists(path), 'path not exist {}'.format(path)
    assert ext is not None, 'ext is None'
    if os.path.isfile(path):
        return [path]
    file_path_list = []
    for root, _, files in os.walk(path):
        for file in files:
            try:
                if file.rsplit('.')[-1].lower() in ext:
                    file_path_list.append(os.path.join(root, file))
            except Exception as e:
                pass
    return file_path_list


class TestGenerator(unittest.TestCase):

    def setUp(self):
        self.debug_flag = False
        self.label_list = ['Text', 'Title', 'Figure', 'Table', 'List', 'Header', 'Footer']
        self.publaynet_label_list = ['text', 'title', 'figure', 'table', 'list']
        self.doclaynet_label_list = [
            'Text', 'Title', 'Picture', 'Table', 'List-item', 'Page-header', 'Page-footer', 'Section-header',
            'Footnote', 'Caption', 'Formula'
        ]
        self.class_color_list = [[0, 0, 255], [0, 255, 0], [255, 0, 255], [0, 255, 255], [0, 0, 0], [255, 0, 0],
                                 [255, 255, 0], [0, 0, 120], [0, 120, 0], [120, 0, 0], [120, 120, 0], [0, 120, 120],
                                 [120, 0, 120]]

    def test_convert_DocLayNet_2_graph(self):
        debug_dir = '/dataset_ws1/dataset/layout/DocLayNet_core_debug'
        ocr_dir = '/open-dataset/OD-layout/DocLayNet_core/ocr_results'
        image_dir = '/open-dataset/OD-layout/DocLayNet_core/images'
        out_dir = '/open-dataset/OD-layout/DocLayNet_core_graph_labels'
        log_file = open('/dataset_ws1/dataset/layout/error_DocLayNet_core.txt', 'a+')
        label_dir = '/open-dataset/OD-layout/DocLayNet_core/COCO/'
        label_path_list = get_file_path_list(label_dir, ['json'])
        for label_path in label_path_list:
            with open(label_path) as f:
                coco_label_data = json.load(f)
            split = os.path.basename(label_path).replace('.json', '')
            categories = coco_label_data['categories']
            label_list_dict = {}
            for annotation in coco_label_data['annotations']:
                if annotation['image_id'] not in label_list_dict:
                    label_list_dict[annotation['image_id']] = [annotation]
                else:
                    label_list_dict[annotation['image_id']].append(annotation)
            error_debug_flag = False
            for image_data in tqdm(coco_label_data['images']):
                out_path = os.path.join(out_dir, split, 'graph_labels',
                                        image_data['file_name'].replace('.png', '.json'))
                if not os.path.exists(out_path):
                    img_path = os.path.join(image_dir, image_data['file_name'])
                    ocr_path = os.path.join(ocr_dir, image_data['file_name'].replace('.png', '.json'))
                    print(out_path)
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)
                    with open(ocr_path) as f:
                        all_ocr_data = json.load(f)
                    label_list = label_list_dict.get(image_data['id'], [])
                    if len(label_list) == 0:
                        continue
                    result_data = []
                    for j, ocr_data in enumerate(all_ocr_data['cells']):
                        if ocr_data['bbox'][2] <= 0 or ocr_data['bbox'][3] <= 0:
                            continue
                        iou_list = []
                        ocr_bbox = [
                            ocr_data['bbox'][0], ocr_data['bbox'][1], ocr_data['bbox'][0] + ocr_data['bbox'][2],
                            ocr_data['bbox'][1] + ocr_data['bbox'][3]
                        ]
                        for i, label_data in enumerate(label_list):
                            if label_data['bbox'][2] <= 0 or label_data['bbox'][3] <= 0:
                                iou_list.append(-1)
                            else:
                                label_bbox = [
                                    label_data['bbox'][0], label_data['bbox'][1],
                                    label_data['bbox'][0] + label_data['bbox'][2],
                                    label_data['bbox'][1] + label_data['bbox'][3]
                                ]
                                iou = max(get_iou(ocr_bbox, label_bbox), get_iou(label_bbox, ocr_bbox))
                                iou_list.append(iou)
                        index = iou_list.index(max(iou_list))
                        category_id = label_list[index]['category_id']
                        label = categories[category_id - 1]['name']
                        item = {
                            'text_coor': list(map(int, ocr_bbox)),
                            'label': label + '_' + str(index),
                            'content': ocr_data['text'],
                        }
                        if max(iou_list) < 0.55:
                            log_string = 'small_iou:{},max_iou={},{}\n'.format(img_path, max(iou_list), item)
                            # print(log_string)
                            log_file.write(log_string)
                            error_debug_flag = True
                        elif len(iou_list) >= 2 and max(iou_list) - sorted(iou_list)[-2] < 0.5:
                            log_string = 'similar_iou:{},max_iou={},second_iou={},{}\n'.format(
                                img_path, max(iou_list),
                                sorted(iou_list)[-2], item)
                            # print(log_string)
                            log_file.write(log_string)
                            error_debug_flag = True
                        else:
                            result_data.append(item)
                    if self.debug_flag:
                        if random.random() < 0.000 or error_debug_flag:
                            debug_out_path = os.path.join(debug_dir, os.path.basename(img_path))
                            os.makedirs(os.path.dirname(debug_out_path), exist_ok=True)
                            img = cv2.imread(img_path)
                            color_list = [(np.random.randint(0, 255), np.random.randint(0,
                                                                                        255), np.random.randint(0, 255))
                                          for i in range(len(label_list))]
                            for data in result_data:
                                color = color_list[int(data['label'].split('_')[1])]
                                cv2.rectangle(img, (data['text_coor'][0], data['text_coor'][1]),
                                              (data['text_coor'][2], data['text_coor'][3]), color, 3)
                            for label_data in label_list:
                                label_index = label_data['category_id']
                                label = categories[label_index - 1]['name']
                                label = self.doclaynet_label_list.index(label)
                                label_bbox = [
                                    label_data['bbox'][0], label_data['bbox'][1],
                                    label_data['bbox'][0] + label_data['bbox'][2],
                                    label_data['bbox'][1] + label_data['bbox'][3]
                                ]
                                cv2.rectangle(img, (int(label_bbox[0]), int(label_bbox[1])),
                                              (int(label_bbox[2]), int(label_bbox[3])), self.class_color_list[label], 2)
                            cv2.imwrite(debug_out_path, img)
                    with open(out_path, "w", encoding='utf-8') as f:
                        json.dump({
                            'img_data_list': result_data,
                            'doc_category': image_data['doc_category']
                        },
                                  f,
                                  ensure_ascii=False,
                                  indent=2)
        log_file.close()

    def test_convert_FUNSD_2_graph(self):
        from functools import cmp_to_key

        def cmp_text_chunk(item1, item2):
            bbox1 = np.array(item1[1]['text_coor']).reshape(2, 2)
            bbox2 = np.array(item2[1]['text_coor']).reshape(2, 2)
            return sort_point(bbox1, bbox2)

        input_dir = '/open-dataset/OD-layout/FUNSD'
        output_dir_word = '/open-dataset/OD-layout/FUNSD_word_graph_labels'
        output_dir_entity = '/open-dataset/OD-layout/FUNSD_entity_graph_labels'
        img_path_list = get_file_path_list(os.path.join(input_dir), ['jpg', 'png', 'jpeg'])
        for img_path in tqdm(img_path_list):
            out_path_word = img_path.replace(input_dir, output_dir_word).replace('/images/', '/graph_labels/').replace(
                '.jpg', '.json').replace('.jpeg', '.json').replace('.png', '.json')
            out_path_entity = img_path.replace(input_dir,
                                               output_dir_entity).replace('/images/', '/graph_labels/').replace(
                                                   '.jpg', '.json').replace('.jpeg', '.json').replace('.png', '.json')
            if not os.path.exists(out_path_word) or not os.path.exists(out_path_entity):
                print(img_path)
                os.makedirs(os.path.dirname(out_path_word), exist_ok=True)
                os.makedirs(os.path.dirname(out_path_entity), exist_ok=True)
                label_path = img_path.replace('/images/', '/annotations/').replace('.jpg', '.json').replace(
                    '.jpeg', '.json').replace('.png', '.json')
                with open(label_path) as f:
                    label_list = json.load(f)['form']
                result_data_word = []
                result_data_entity = []
                for label_data in label_list:
                    for word in label_data['words']:
                        item = {
                            'text_coor': word['box'],
                            'label': label_data['label'] + '_' + str(label_data['id']),
                            'content': word['text'],
                        }
                        result_data_word.append(item)
                    item = {
                        'text_coor': label_data['box'],
                        'label': label_data['label'] + '_' + str(label_data['id']),
                        'content': label_data['text'],
                        'linking': label_data['linking']
                    }
                    result_data_entity.append(item)
                # 排序
                result_data_word = [
                    item
                    for i, item in sorted(enumerate(result_data_word), key=cmp_to_key(cmp_text_chunk), reverse=True)
                ]
                result_data_entity = [
                    item
                    for i, item in sorted(enumerate(result_data_entity), key=cmp_to_key(cmp_text_chunk), reverse=True)
                ]
                with open(out_path_word, "w", encoding='utf-8') as f:
                    json.dump({'img_data_list': result_data_word}, f, ensure_ascii=False, indent=2)

                with open(out_path_entity, "w", encoding='utf-8') as f:
                    json.dump({'img_data_list': result_data_entity}, f, ensure_ascii=False, indent=2)

    def test_convert_Publaynet_2_graph(self):
        from functools import cmp_to_key

        def cmp_text_chunk(item1, item2):
            bbox1 = np.array(item1[1]['text_coor']).reshape(2, 2)
            bbox2 = np.array(item2[1]['text_coor']).reshape(2, 2)
            return sort_point(bbox1, bbox2)

        input_dir = '/open-dataset/OD-layout/publaynet'
        debug_dir = '/dataset_ws1/dataset/layout/publaynet_debug'
        output_dir_word = '/open-dataset/OD-layout/publaynet_word_graph_labels'
        output_dir_entity = '/open-dataset/OD-layout/publaynet_entity_graph_labels'
        log_file = open('/dataset_ws1/dataset/layout/error_publaynet.txt', 'a+')
        label_path_list = get_file_path_list(input_dir, ['json'])
        for label_path in label_path_list:
            if 'train' in label_path:
                continue
            with open(label_path) as f:
                coco_label_data = json.load(f)
            split = os.path.basename(label_path).replace('.json', '')
            categories = coco_label_data['categories']
            label_list_dict = {}
            for annotation in coco_label_data['annotations']:
                if annotation['image_id'] not in label_list_dict:
                    label_list_dict[annotation['image_id']] = [annotation]
                else:
                    label_list_dict[annotation['image_id']].append(annotation)
            error_debug_flag = False
            for image_data in tqdm(coco_label_data['images']):
                out_path_word = os.path.join(output_dir_word, split, 'graph_labels',
                                             image_data['file_name'].replace('.jpg', '.json'))
                out_path_entity = os.path.join(output_dir_entity, split, 'graph_labels',
                                               image_data['file_name'].replace('.jpg', '.json'))
                if not os.path.exists(out_path_entity) or not os.path.exists(out_path_word):
                    print(image_data['file_name'])
                    img_path = os.path.join(input_dir, split, 'images', image_data['file_name'])
                    pdf_path = os.path.join(input_dir, split, 'pdfs', image_data['file_name'].replace('.jpg', '.pdf'))
                    os.makedirs(os.path.dirname(out_path_word), exist_ok=True)
                    os.makedirs(os.path.dirname(out_path_entity), exist_ok=True)
                    label_list = label_list_dict.get(image_data['id'], [])
                    if len(label_list) == 0:
                        log_string = 'labal_list empty:{}\n'.format(img_path)
                        log_file.write(log_string)
                        continue
                    try:
                        text_block_list, words_list = get_ocr_data_from_pdf(pdf_path)
                    except:
                        log_string = 'fail to read_pdf:{}\n'.format(img_path)
                        log_file.write(log_string)
                        continue
                    result_data_word = []
                    for j, word in enumerate(words_list):
                        word_bbox = [word[0], word[1], word[2], word[3]]
                        if word_bbox[2] <= word_bbox[0] or word_bbox[3] <= word_bbox[1]:
                            continue
                        iou_list = []
                        for i, label_data in enumerate(label_list):
                            if label_data['bbox'][2] <= 0 or label_data['bbox'][3] <= 0:
                                iou_list.append(-1)
                            else:
                                label_bbox = [
                                    label_data['bbox'][0], label_data['bbox'][1],
                                    label_data['bbox'][0] + label_data['bbox'][2],
                                    label_data['bbox'][1] + label_data['bbox'][3]
                                ]
                                iou = max(get_iou(word_bbox, label_bbox), get_iou(label_bbox, word_bbox))
                                iou_list.append(iou)
                        index = iou_list.index(max(iou_list))
                        category_id = label_list[index]['category_id']
                        label = categories[category_id - 1]['name']
                        item = {
                            'text_coor': list(map(int, word_bbox)),
                            'label': label + '_' + str(index),
                            'content': word[4],
                        }
                        if max(iou_list) < 0.55:
                            log_string = 'word:small_iou:{},max_iou={},{}\n'.format(img_path, max(iou_list), item)
                            log_file.write(log_string)
                            error_debug_flag = True
                        elif len(iou_list) >= 2 and max(iou_list) - sorted(iou_list)[-2] < 0.5:
                            log_string = 'word:similar_iou:{},max_iou={},second_iou={},{}\n'.format(
                                img_path, max(iou_list),
                                sorted(iou_list)[-2], item)
                            log_file.write(log_string)
                            error_debug_flag = True
                        else:
                            result_data_word.append(item)
                    result_data_entity = []
                    for j, text_block in enumerate(text_block_list):
                        if text_block['type'] != 0:
                            continue
                        for ocr_data in text_block['lines']:
                            ocr_data['text'] = ''.join([span['text'] for span in ocr_data['spans']])
                            if ocr_data['bbox'][2] <= ocr_data['bbox'][0] or ocr_data['bbox'][3] <= ocr_data['bbox'][1]:
                                continue
                            iou_list = []
                            for i, label_data in enumerate(label_list):
                                if label_data['bbox'][2] <= 0 or label_data['bbox'][3] <= 0:
                                    iou_list.append(-1)
                                else:
                                    label_bbox = [
                                        label_data['bbox'][0], label_data['bbox'][1],
                                        label_data['bbox'][0] + label_data['bbox'][2],
                                        label_data['bbox'][1] + label_data['bbox'][3]
                                    ]
                                    iou = max(get_iou(ocr_data['bbox'], label_bbox),
                                              get_iou(label_bbox, ocr_data['bbox']))
                                    iou_list.append(iou)
                            index = iou_list.index(max(iou_list))
                            category_id = label_list[index]['category_id']
                            label = categories[category_id - 1]['name']
                            item = {
                                'text_coor': list(map(int, ocr_data['bbox'])),
                                'label': label + '_' + str(index),
                                'content': ocr_data['text'],
                            }
                            if max(iou_list) < 0.55:
                                log_string = 'entity:small_iou:{},max_iou={},{}\n'.format(img_path, max(iou_list), item)
                                # print(log_string)
                                log_file.write(log_string)
                                error_debug_flag = True
                            elif len(iou_list) >= 2 and max(iou_list) - sorted(iou_list)[-2] < 0.5:
                                log_string = 'entity:similar_iou:{},max_iou={},second_iou={},{}\n'.format(
                                    img_path, max(iou_list),
                                    sorted(iou_list)[-2], item)
                                # print(log_string)
                                log_file.write(log_string)
                                error_debug_flag = True
                            else:
                                result_data_entity.append(item)
                    if self.debug_flag:
                        if random.random() < 0.000 or error_debug_flag:
                            debug_out_path = os.path.join(debug_dir, os.path.basename(img_path))
                            os.makedirs(os.path.dirname(debug_out_path), exist_ok=True)
                            img = cv2.imread(img_path)
                            color_list = [(np.random.randint(0, 255), np.random.randint(0,
                                                                                        255), np.random.randint(0, 255))
                                          for i in range(len(label_list))]
                            word_img = copy.deepcopy(img)
                            for data in result_data_entity:
                                color = color_list[int(data['label'].split('_')[1])]
                                cv2.rectangle(img, (data['text_coor'][0], data['text_coor'][1]),
                                              (data['text_coor'][2], data['text_coor'][3]), color, 3)
                            cv2.imwrite(debug_out_path, img)
                            debug_out_path = os.path.join(debug_dir, os.path.basename(img_path))
                            for data in result_data_word:
                                color = color_list[int(data['label'].split('_')[1])]
                                cv2.rectangle(word_img, (data['text_coor'][0], data['text_coor'][1]),
                                              (data['text_coor'][2], data['text_coor'][3]), color, 3)
                            cv2.imwrite(debug_out_path.replace('.jpg', '_word.jpg'), word_img)
                    # 排序
                    result_data_word = [
                        item
                        for i, item in sorted(enumerate(result_data_word), key=cmp_to_key(cmp_text_chunk), reverse=True)
                    ]
                    result_data_entity = [
                        item for i, item in sorted(
                            enumerate(result_data_entity), key=cmp_to_key(cmp_text_chunk), reverse=True)
                    ]
                    try:
                        with open(out_path_word, "w", encoding='utf-8') as f:
                            json.dump({'img_data_list': result_data_word}, f, ensure_ascii=False, indent=2)
                        with open(out_path_entity, "w", encoding='utf-8') as f:
                            json.dump({'img_data_list': result_data_entity}, f, ensure_ascii=False, indent=2)
                    except:
                        log_string = 'fail to write:{}\n'.format(img_path)
                        log_file.write(log_string)

    def test_convert_graphlabels_2_coco(self):
        DATA_DIR = '/open-dataset/OD-layout/publaynet_entity_graph_labels/val'
        coco_path = '/open-dataset/OD-layout/publaynet_entity_graph_labels/val.json'
        label_list = self.publaynet_label_list
        # DATA_DIR = '/open-dataset/OD-layout/DocLayNet_core_graph_labels/val'
        # coco_path = '/open-dataset/OD-layout/DocLayNet_core_graph_labels/val.json'
        # label_list = self.doclaynet_label_list

        coco_data = {
            "images": [],
            "annotations": [],
            "categories": [{
                'id': i,
                'name': label
            } for i, label in enumerate(label_list)],
        }
        od_instance_count = 0
        image_id = 0
        img_path_list = get_file_path_list(DATA_DIR, ['json'])
        for i, label_path in tqdm(enumerate(img_path_list)):
            coco_data["images"].append({
                "file_name": label_path,
                # "height": img.height,
                # "width": img.width,
                "id": image_id,
            })
            with open(label_path) as f:
                label_data_list = json.load(f)['img_data_list']
            label_dict = {}
            for i, item in enumerate(label_data_list):
                if item['label'] in label_dict:
                    label_dict[item['label']].append(item['text_coor'])
                else:
                    label_dict[item['label']] = [item['text_coor']]
            for key, box_list in label_dict.items():
                label = key.split('_')[0]
                points_array = np.array(box_list).reshape(-1, 2)
                x1, y1 = float(min(points_array[:, 0])), float(min(points_array[:, 1]))
                x2, y2 = float(max(points_array[:, 0])), float(max(points_array[:, 1]))
                bbox = [x1, y1, x2 - x1, y2 - y1]
                segmentation = [x1, y1, x2, y1, x2, y2, x1, y2]
                coco_data["annotations"].append({
                    "segmentation": [segmentation],
                    "area": bbox[2] * bbox[3],
                    "iscrowd": 0,
                    "image_id": image_id,
                    "bbox": bbox,
                    "score": 1.0,
                    "category_id": label_list.index(label),
                    "id": od_instance_count,
                })
                od_instance_count += 1
            image_id += 1
        with open(coco_path, "w", encoding='utf-8') as f:
            json.dump(coco_data, f, ensure_ascii=False, indent=2)


def get_ocr_data_from_pdf(pdf_path):
    assert os.path.getsize(pdf_path) != 0, 'error'
    import fitz
    doc = fitz.Document(pdf_path)
    page = doc.load_page(0)
    text_block_list = page.getText(option='dict')['blocks']
    words_list = page.getText(option='words')
    return text_block_list, words_list


def sort_point(points1, points2):
    x10 = np.min(points1[:, 0])
    x11 = np.max(points1[:, 0])
    y10 = np.min(points1[:, 1])
    y11 = np.max(points1[:, 1])

    x20 = np.min(points2[:, 0])
    x21 = np.max(points2[:, 0])
    y20 = np.min(points2[:, 1])
    y21 = np.max(points2[:, 1])

    if y11 <= y20:
        return 1
    elif y21 <= y10:
        return -1
    y_com = min(y11, y21) - max(y10, y20)
    min_h = min(y11 - y10, y21 - y20)
    if y_com / min_h >= 0.5:
        # the same line
        if (x10 + x11) < (x20 + x21):
            return 1
        elif (x10 + x11) > (x20 + x21):
            return -1
        else:
            return 0
    else:
        if x11 <= x20 or x21 <= x10:
            if (y10 + y11) < (y20 + y21):
                return 1
            elif (y10 + y11) > (y20 + y21):
                return -1
            else:
                return 0
        x_com = min(x20, x21) - max(x10, x20)
        min_w = min(x11 - x10, x21 - x20)
        if x_com / min_w >= 0.2 and y_com / min_h >= 0.2:
            # the same line
            if (x10 + x11) < (x20 + x21):
                return 1
            elif (x10 + x11) > (x20 + x21):
                return -1
            else:
                return 0
        else:
            # not the same line
            if (y10 + y11) < (y20 + y21):
                return 1
            elif (y10 + y11) > (y20 + y21):
                return -1
            else:
                return 0


def get_iou(bb1, bb2):
    assert bb1[0] < bb1[2]
    assert bb1[1] < bb1[3]
    assert bb2[0] < bb2[2]
    assert bb2[1] < bb2[3]

    # determine the coordinates of the intersection rectangle
    x_left = max(bb1[0], bb2[0])
    y_top = max(bb1[1], bb2[1])
    x_right = min(bb1[2], bb2[2])
    y_bottom = min(bb1[3], bb2[3])

    if x_right < x_left or y_bottom < y_top:
        return 0.0

    # The intersection of two axis-aligned bounding boxes is always an
    # axis-aligned bounding box
    intersection_area = (x_right - x_left) * (y_bottom - y_top)

    # compute the area of both AABBs
    bb1_area = (bb1[2] - bb1[0]) * (bb1[3] - bb1[1])
    bb2_area = (bb2[2] - bb2[0]) * (bb2[3] - bb2[1])

    # compute the intersection over union by taking the intersection
    # area and dividing it by the sum of prediction + ground-truth
    # areas - the interesection area
    iou = intersection_area / float(bb1_area)
    assert iou >= 0.0
    assert iou <= 1.0
    return iou


def rotate(image, angle):
    h, w = image.shape[:2]
    rad = np.pi / 180 * angle
    center = ((w - 1) // 2, (h - 1) // 2)
    h_new = int(math.ceil(abs(h * math.cos(rad)) + abs(w * math.sin(rad))))
    w_new = int(math.ceil(abs(w * math.cos(rad)) + abs(h * math.sin(rad))))
    rotate_matrix = cv2.getRotationMatrix2D(center, angle=angle, scale=1)
    rotate_matrix[0, 2] += w // 2 + (w_new // 2 - w)
    rotate_matrix[1, 2] += h // 2 + (h_new // 2 - h)
    transform_matrix = rotate_matrix
    dst_size = (w_new, h_new)
    return cv2.warpAffine(image, transform_matrix, dst_size, flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE)
