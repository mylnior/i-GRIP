#!/usr/bin/env python3

import argparse
import multiprocessing
import threading
import torch
import gc
import os
import cv2

from i_grip import RgbdCameras as rgbd
from i_grip import Hands3DDetectors as hd
from i_grip import Object2DDetectors as o2d
from i_grip import ObjectPoseEstimators as ope
from i_grip import Scene_threading as sc
# from i_grip import Scene_nocopy as sc
from i_grip import Plotters3 as pl
from i_grip.utils import kill_gpu_processes

os.environ['CUDA_VISIBLE_DEVICES'] = '0'
def report_gpu():
   print(torch.cuda.list_gpu_processes())
   gc.collect()
   print(torch.cuda.memory_snapshot())
   torch.cuda.empty_cache()


class GraspingDetector:
    def __init__(self, ) -> None:
        dataset = "ycbv"
        self.rgbd_cam = rgbd.RgbdCamera()
        cam_data = self.rgbd_cam.get_device_data()
        self.hand_detector = hd.Hands3DDetector(cam_data,
                                            hd.Hands3DDetector.LIVE_STREAM_MODE)
        plotter = pl.NBPlot()
        # plotter = None
        self.object_detector = o2d.get_object_detector(dataset,
                                                       cam_data)
        self.object_pose_estimator = ope.get_pose_estimator(dataset,
                                                            cam_data,
                                                            use_tracking = True,
                                                            fuse_detections=False)
        self.scene = sc.LiveScene(cam_data,
                              name = 'Full tracking', plotter = plotter)
        self.object_detections = None
        self.is_hands= False
        self.img_for_objects = None
        
        
    def estimate_objects_task(self, start_event, estimate_event):
        while self.rgbd_cam.is_on():
            start_flag = start_event.wait(1)
            if start_flag:
                if estimate_event.wait(1):
                    self.objects_pose = self.object_pose_estimator.estimate(self.img_for_objects, detections = self.object_detections)
                    self.scene.update_objects(self.objects_pose)
                    estimate_event.clear()

    def detect_objects_task(self, start_event, detect_event, estimate_event):
        while self.rgbd_cam.is_on():
            start_flag = start_event.wait(1)
            if start_flag:
                detect_flag = detect_event.wait(1)
                if detect_flag:
                    # self.object_detections = self.object_detector.detect(cv2.flip(self.img,1))
                    self.object_detections = self.object_detector.detect(self.img_for_objects)
                    if self.object_detections is not None:
                        detect_event.clear()
                        estimate_event.set()
                else:
                    self.object_detections = None
    
    def detect_hands_task(self, start_event, detect_hand_event):
        while self.rgbd_cam.is_on():
            start_flag = start_event.wait(1)
            if start_flag:
                detect_flag = detect_hand_event.wait(1)
                if detect_flag:
                    hands = self.hand_detector.get_hands(self.img_for_hands, self.depth_map)
                    # print(f'img_for_hands.shape: {img_for_hands.shape}')    
                    if hands is not None and len(hands)>0:
                        self.scene.update_hands(hands)
                    detect_hand_event.clear()


    def run(self):
        # multiprocessing.set_start_method('spawn')
        print(self.__dict__)
        print('start')
        self.rgbd_cam.start()
        start_event = threading.Event()
        detect_obj_event = threading.Event()
        estimate_event = threading.Event()
        detect_hand_event = threading.Event()
        self.t_obj_d = threading.Thread(target=self.detect_objects_task, args=(start_event, detect_obj_event,estimate_event,))
        self.t_obj_e = threading.Thread(target=self.estimate_objects_task, args=(start_event, estimate_event,))
        self.t_hand = threading.Thread(target=self.detect_hands_task, args=(start_event, detect_hand_event,))
        # self.t_plot = threading.Thread(target=self.plot_task)
        # self.t_plot.start()
        self.t_obj_d.start()
        self.t_obj_e.start()
        self.t_hand.start()
        started = True
        obj_path = './YCBV_test_pictures/javel.png'
        obj_path2 = './YCBV_test_pictures/mustard_front.png'
        # obj_path = './YCBV_test_pictures/YCBV.png'
        obj_img = cv2.imread(obj_path)
        obj_img = cv2.resize(obj_img, (int(obj_img.shape[1]/2), int(obj_img.shape[0]/2)))
        obj_img2 = cv2.imread(obj_path2)
        obj_img2 = cv2.resize(obj_img2, (int(obj_img2.shape[1]/3), int(obj_img2.shape[0]/3)))
        while self.rgbd_cam.is_on():
            # pl.plot()
            k = cv2.waitKey(2)
            success, img, self.depth_map = self.rgbd_cam.next_frame()
            if not success:
                self.img_for_objects = None
                continue     
            else:
                img[0:obj_img.shape[0], 0:obj_img.shape[1]] = obj_img
                img[0:obj_img2.shape[0], img.shape[1]-obj_img2.shape[1]:] = obj_img2
                self.img_for_hands = img.copy()
                # img_for_hands = cv2.resize(img_for_hands, (int(self.hand_detector.resolution[0]/2), int(self.hand_detector.resolution[1]/2)))
                self.img_for_hands = cv2.cvtColor(self.img_for_hands, cv2.COLOR_RGB2BGR)
                self.img_for_hands.flags.writeable = False
                detect_hand_event.set()
                if estimate_event.is_set() or detect_obj_event.is_set():
                    self.img_for_objects = img.copy()
                    
                    # incorporate obj_img in img_for_objects
                    self.img_for_objects = cv2.cvtColor(self.img_for_objects, cv2.COLOR_RGB2BGR)
                    self.img_for_objects.flags.writeable = False
                if started:
                    start_event.set()
                    detect_obj_event.set()
                    started = False
                if not estimate_event.is_set():
                    estimate_event.set()
                
                # Avant de commencer à utiliser la mémoire GPU
                torch.cuda.empty_cache()  # Pour libérer toute mémoire inutilisée

                # Utilisez cette ligne pour obtenir la mémoire GPU utilisée en octets
                gpu_memory_used = torch.cuda.memory_allocated()

                # Utilisez cette ligne pour obtenir la mémoire GPU réservée en octets (y compris la mémoire non allouée)
                gpu_memory_reserved = torch.cuda.memory_reserved()

                # Convertissez les valeurs en méga-octets (Mo) pour une meilleure lisibilité
                gpu_memory_used_mb = gpu_memory_used / 1024 / 1024
                gpu_memory_reserved_mb = gpu_memory_reserved / 1024 / 1024


                # print(f"GPU Memory Used: {gpu_memory_used_mb:.2f} MB")
                # print(f"GPU Memory Reserved: {gpu_memory_reserved_mb:.2f} MB")
                
            if k == 32:
                print('DETEEEEEEEEEEEEEEEEEECT')
                detect_obj_event.set()
            self.scene.render(img)
            cv2.imshow('render_img', img)
            if k == 27:
                print('end')
                self.stop()
                break
        exit()

    def stop(self):
        self.rgbd_cam.stop()
        self.t_obj_d.join()
        self.t_obj_e.join()
        self.t_hand.join()
        self.scene.stop()
        cv2.destroyAllWindows()
        self.hand_detector.stop()
        self.object_detector.stop()
        self.object_pose_estimator.stop()
        exit()


if __name__ == '__main__':
    
    parser = argparse.ArgumentParser()
    parser.add_argument('-hd', '--hand_detection', choices=['mediapipe', 'depthai', 'hybridOAKMediapipe'],
                        default = 'hybridOAKMediapipe', help="Hand pose reconstruction solution")
    parser.add_argument('-od', '--object_detection', choices=['cosypose, megapose'],
                        default = 'cosypose', help="Object pose reconstruction detection")
    args = vars(parser.parse_args())

    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    
    print('start')
    report_gpu()
    kill_gpu_processes()
    i_grip = GraspingDetector()
    i_grip.run()
